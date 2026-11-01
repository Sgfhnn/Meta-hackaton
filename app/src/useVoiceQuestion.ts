// Record what the user says to the assistant (expo-audio, with level metering). Ways in:
//   - hands-free ('auto'): the app opens the microphone by itself after it has finished speaking.
//     The level meter decides: speech starts when the level rises above the room's noise, the
//     turn ends after ~1.2 s of quiet (max 12 s of speech). Nothing said within 8 s: stop quietly.
//     If the app starts speaking before the user does, the take is thrown away (never record the
//     app's own voice); the caller listens again when it is quiet.
//   - tap: tap the screen, speak, tap again (TalkBack: double tap twice).
//   - hold: hold the screen while speaking and let go.
// A tap or hold during a hands-free take turns it into a manual one (keeps the audio so far).
// (expo-av is gone from this Expo SDK; expo-audio's recorder has the same metering.)

import {
  getRecordingPermissionsAsync,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  type RecordingOptions,
} from 'expo-audio';
import { useEffect, useRef, useState } from 'react';

const MAX_MS = 12_000; // a manual question (docs/api.md: keep questions short)
const MIN_MS = 600; // shorter than this is a slip, not a question
export const AUTO = {
  noSpeechMs: 8_000, // nothing said: go idle quietly
  silenceMs: 1_200, // quiet after speech: the turn is over
  maxSpeechMs: 12_000,
  tickMs: 100,
  calibrateMs: 300, // the first samples set the room's noise floor
  riseDb: 10, // speech = this far above the floor...
  minSpeechDb: -50, // ...and at least this loud
  onsetTicks: 2, // ...for 200 ms
};
const OPTIONS: RecordingOptions = { ...RecordingPresets.HIGH_QUALITY, isMeteringEnabled: true };
// Every field set each time (fields left out keep or reset to defaults that differ per platform).
// 'mixWithOthers': no audio focus request, so a clip is never held back by focus.
const RECORDING_MODE = {
  allowsRecording: true,
  playsInSilentMode: true,
  shouldRouteThroughEarpiece: false,
  shouldPlayInBackground: false,
  interruptionMode: 'mixWithOthers',
} as const;
const PLAYBACK_MODE = { ...RECORDING_MODE, allowsRecording: false } as const;

export type ListenMode = 'tap' | 'hold' | 'auto';
export type Recording =
  | { kind: 'ok'; uri: string; auto: boolean }
  | { kind: 'denied' } // no microphone permission
  | { kind: 'short' }
  | { kind: 'failed' }
  | { kind: 'nothing' } // hands-free: nobody spoke
  | { kind: 'interrupted' }; // hands-free: the app started speaking first, take thrown away

type StopReason = 'manual' | 'silence' | 'max' | 'no speech' | 'app speaking' | 'cancelled';

export function useVoiceQuestion(onDone: (recording: Recording) => void) {
  const recorder = useAudioRecorder(OPTIONS);
  const [listening, setListening] = useState(false);
  const wanted = useRef(false); // the user still wants to record (not let go yet)
  const active = useRef(false);
  const mode = useRef<ListenMode>('tap');
  const startedAt = useRef(0);
  const speechAt = useRef(0); // when speech began (0 = not yet)
  const loudAt = useRef(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoStop = useRef<ReturnType<typeof setTimeout> | null>(null);
  const appSpeaking = useRef<() => Promise<boolean>>(async () => false);
  const askedPermission = useRef(false);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone; // the latest callback, for recordings that end later
  });
  useEffect(() => () => clearTimers(), []);

  function clearTimers() {
    if (timer.current) clearInterval(timer.current);
    if (autoStop.current) clearTimeout(autoStop.current);
    timer.current = null;
    autoStop.current = null;
  }

  async function finish(reason: StopReason): Promise<void> {
    wanted.current = false;
    if (!active.current) return;
    active.current = false;
    clearTimers();
    setListening(false);
    const wasAuto = mode.current === 'auto';
    const spoke = speechAt.current > 0;
    const length = Date.now() - startedAt.current;
    if (wasAuto) console.log(`[birr] listen: auto-stop (${reason})`);
    try {
      await recorder.stop();
    } catch (e) {
      console.warn('[birr] recorder.stop failed', e); // no file: reported as failed below
    }
    try {
      // Play answers on the speaker again (voice.ts sets this again before every clip).
      await setAudioModeAsync(PLAYBACK_MODE);
    } catch (e) {
      console.warn('[birr] audio mode reset failed', e);
    }
    if (reason === 'cancelled') return;
    if (wasAuto) {
      if (reason === 'app speaking') return done.current({ kind: 'interrupted' });
      if (!spoke) return done.current({ kind: 'nothing' });
      return done.current(recorder.uri ? { kind: 'ok', uri: recorder.uri, auto: true } : { kind: 'failed' });
    }
    if (length < MIN_MS) return done.current({ kind: 'short' });
    done.current(recorder.uri ? { kind: 'ok', uri: recorder.uri, auto: false } : { kind: 'failed' });
  }

  /** Stop and send (manual stop, or the hands-free take if speech was heard). */
  function stop(): Promise<void> {
    return finish('manual');
  }

  /** Stop and throw the audio away. */
  function cancel(): Promise<void> {
    return finish('cancelled');
  }

  // Hands-free: watch the level meter.
  function watchLevel() {
    let floor: number | null = null;
    const calib: number[] = [];
    let above = 0;
    let ticks = 0;
    let checking = false;
    timer.current = setInterval(() => {
      if (!active.current || mode.current !== 'auto') return;
      const now = Date.now();
      ticks += 1;
      let level: number | undefined;
      try {
        level = recorder.getStatus().metering;
      } catch {
        level = undefined;
      }
      if (level === undefined || Number.isNaN(level)) {
        if (now - startedAt.current > 1_000) {
          console.log('[birr] listen: no level meter on this phone, hands-free off for this take');
          void finish('no speech');
        }
        return;
      }
      if (floor === null) {
        calib.push(level);
        if (now - startedAt.current < AUTO.calibrateMs) return;
        floor = Math.min(...calib);
      }
      const loud = level >= Math.max(floor + AUTO.riseDb, AUTO.minSpeechDb);
      if (!speechAt.current) {
        above = loud ? above + 1 : 0;
        if (above >= AUTO.onsetTicks) {
          speechAt.current = now;
          loudAt.current = now;
          console.log(`[birr] listen: speech (level ${level.toFixed(0)} dB, floor ${floor.toFixed(0)} dB)`);
          return;
        }
        if (!loud) floor = 0.95 * floor + 0.05 * level; // follow the room slowly
        if (now - startedAt.current > AUTO.noSpeechMs) {
          void finish('no speech');
          return;
        }
        // Never keep the app's own voice: if it starts talking first, throw the take away.
        if (ticks % 3 === 0 && !checking) {
          checking = true;
          appSpeaking
            .current()
            .then((speaking) => {
              if (speaking && active.current && mode.current === 'auto' && !speechAt.current) void finish('app speaking');
            })
            .finally(() => {
              checking = false;
            });
        }
        return;
      }
      if (level >= floor + AUTO.riseDb / 2) loudAt.current = now; // hysteresis: quieter speech still counts
      if (now - loudAt.current > AUTO.silenceMs) void finish('silence');
      else if (now - speechAt.current > AUTO.maxSpeechMs) void finish('max');
    }, AUTO.tickMs);
  }

  /** Turn a hands-free take into a manual one (the user tapped or held during it). */
  function takeOver(next: 'tap' | 'hold') {
    if (!active.current || mode.current !== 'auto') return;
    mode.current = next;
    wanted.current = true;
    clearTimers();
    console.log(`[birr] listen: manual (${next})`);
    autoStop.current = setTimeout(() => void finish('max'), MAX_MS);
  }

  async function start(
    next: ListenMode = 'tap',
    opts: { appSpeaking?: () => Promise<boolean> } = {},
  ): Promise<void> {
    if (active.current) {
      if (next !== 'auto') takeOver(next);
      return;
    }
    if (wanted.current) return; // already starting, or asking for permission
    wanted.current = true;
    mode.current = next;
    speechAt.current = 0;
    if (opts.appSpeaking) appSpeaking.current = opts.appSpeaking;
    const asked = Date.now();
    let permission = await getRecordingPermissionsAsync();
    if (!permission.granted && (next !== 'auto' || (!askedPermission.current && permission.canAskAgain))) {
      // Hands-free asks for the microphone once per launch, never over and over.
      askedPermission.current = true;
      permission = await requestRecordingPermissionsAsync();
    }
    if (!permission.granted) {
      wanted.current = false;
      if (next === 'auto') {
        console.log('[birr] listen: no microphone permission, hands-free off');
        done.current({ kind: 'nothing' });
      } else done.current({ kind: 'denied' });
      return;
    }
    // The first time, the permission dialog takes the press: the user lets go to answer it.
    // Say how to ask ("hold the screen while you speak").
    if (!wanted.current) {
      if (mode.current !== 'auto') done.current({ kind: 'short' });
      return;
    }
    try {
      await setAudioModeAsync(RECORDING_MODE);
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch (e) {
      console.warn('[birr] recording failed to start', e);
      wanted.current = false;
      done.current(mode.current === 'auto' ? { kind: 'nothing' } : { kind: 'failed' });
      return;
    }
    active.current = true;
    startedAt.current = Date.now();
    console.log(`[birr] recording started after ${startedAt.current - asked} ms`);
    setListening(true);
    if (mode.current === 'auto') {
      console.log('[birr] listen: auto-start');
      watchLevel();
      return;
    }
    autoStop.current = setTimeout(() => void finish('max'), MAX_MS);
    // Let go while the recorder was still starting: stop now instead of recording for MAX_MS.
    if (!wanted.current) void finish('manual');
  }

  /**
   * Ask for the microphone now (first launch, right after the camera). Counts as this launch's
   * one ask, so hands-free listening after the greeting does not open the dialog again.
   */
  async function askPermission(): Promise<boolean> {
    askedPermission.current = true;
    let permission = await getRecordingPermissionsAsync();
    if (!permission.granted && permission.canAskAgain) permission = await requestRecordingPermissionsAsync();
    return permission.granted;
  }

  /** The app is about to play a clip: throw away a hands-free take that has heard nothing yet. */
  function yieldToApp(): Promise<void> {
    if (active.current && mode.current === 'auto' && !speechAt.current) return finish('app speaking');
    return Promise.resolve();
  }

  return {
    listening,
    start,
    stop,
    cancel,
    yieldToApp,
    askPermission,
    /** A hands-free take is running. */
    isAuto: () => active.current && mode.current === 'auto',
    /** The hands-free take has heard speech. */
    heardSpeech: () => speechAt.current > 0,
  };
}
