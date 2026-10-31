// Record a short spoken question with the microphone (expo-audio). Two ways in:
// hold the screen and let go (start + stop), or the Ask button, tapped twice (which TalkBack
// users can reach). Recording also stops by itself after MAX_MS.

import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder } from 'expo-audio';
import { useEffect, useRef, useState } from 'react';

const MAX_MS = 8_000; // docs/api.md: a question is at most 10 s
const MIN_MS = 600; // shorter than this is a slip, not a question

export type Recording =
  | { kind: 'ok'; uri: string }
  | { kind: 'denied' } // no microphone permission
  | { kind: 'short' }
  | { kind: 'failed' };

export function useVoiceQuestion(onDone: (recording: Recording) => void) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [listening, setListening] = useState(false);
  const wanted = useRef(false); // the user still wants to record (not let go yet)
  const active = useRef(false);
  const startedAt = useRef(0);
  const autoStop = useRef<ReturnType<typeof setTimeout> | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone; // the latest callback, for recordings that end later
  });

  async function stop(): Promise<void> {
    wanted.current = false;
    if (!active.current) return;
    active.current = false;
    if (autoStop.current) clearTimeout(autoStop.current);
    setListening(false);
    const length = Date.now() - startedAt.current;
    try {
      await recorder.stop();
    } catch (e) {
      console.warn('[birr] recorder.stop failed', e); // no file: reported as failed below
    }
    try {
      await setAudioModeAsync({ allowsRecording: false }); // play answers on the speaker again
    } catch (e) {
      console.warn('[birr] audio mode reset failed', e);
    }
    if (length < MIN_MS) {
      done.current({ kind: 'short' });
      return;
    }
    done.current(recorder.uri ? { kind: 'ok', uri: recorder.uri } : { kind: 'failed' });
  }

  async function start(): Promise<void> {
    if (active.current || wanted.current) return; // already recording, or asking for permission
    wanted.current = true;
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      wanted.current = false;
      done.current({ kind: 'denied' });
      return;
    }
    // The first time, the permission dialog takes the press: the user lets go to answer it.
    // Say how to ask ("hold the screen while you speak").
    if (!wanted.current) {
      done.current({ kind: 'short' });
      return;
    }
    try {
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch (e) {
      console.warn('[birr] recording failed to start', e);
      wanted.current = false;
      done.current({ kind: 'failed' });
      return;
    }
    active.current = true;
    startedAt.current = Date.now();
    setListening(true);
    autoStop.current = setTimeout(() => void stop(), MAX_MS);
    // Let go while the recorder was still starting: stop now instead of recording for MAX_MS.
    if (!wanted.current) void stop();
  }

  return { listening, start, stop };
}
