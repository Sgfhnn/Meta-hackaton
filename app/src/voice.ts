// Spoken output. The backend writes the answers (docs/api.md: the app speaks `speech` word for
// word); the short prompts below are the app's own. English goes through the phone's text-to-speech.
// Amharic and Oromo play as clips the backend made with Meta MMS-TTS (most phones have no
// Amharic text-to-speech voice, so a clip that does not play would mean English).
//
// Clips, made to work on real phones and not only the emulator:
//   - every clip is downloaded to a cache file first and played from the file (no streaming);
//   - a fresh player per clip (no createAudioPlayer(null) + replace());
//   - before each clip the audio mode is set for playback: speaker (not the earpiece), plays in
//     silent mode, and no audio focus request ('mixWithOthers'), so a focus refusal can never
//     leave the player paused without a word; a hands-free take that has heard nothing yet is
//     thrown away first (it listens again once the clip is over);
//   - "started" = a status event, or player.playing / currentTime polled every 100 ms;
//   - a non-English clip that does not start is tried once more with a fresh player (from the
//     server if the cached file was the problem). Only then the phone's English voice speaks,
//     with '[birr] clip failed twice' in the log.

import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import * as Speech from 'expo-speech';
import { Directory, File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';

import { API_URL } from './scan';
import type { Lang, PhraseKey, Phrases, Speech as SpeechText } from './types';

const LOCALE: Record<Lang, string> = { en: 'en-US', am: 'am-ET', om: 'om-ET' };
// A clip played from a file has started well within this; else try a fresh player.
const CLIP_START_MS = 4000;
// Streaming from the server (only when the download failed): mobile data can be slow.
const CLIP_STREAM_START_MS = 8000;
// Downloading an answer clip before it plays (100-350 KB).
const CLIP_DOWNLOAD_MS = 15_000;
// Waiting for GET /phrases before saying a prompt in English instead.
const PHRASES_WAIT_MS = 8000;

// App-side prompts in English. The backend serves the same keys translated (GET /phrases).
export const PROMPTS: Record<PhraseKey, string> = {
  counting: 'Counting.',
  stillCounting: 'Still counting.',
  failed: 'Sorry, I could not count that. Please tap to try again.',
  noNetwork: 'I cannot reach the server. Check the internet connection and tap to try again.',
  giveUp: 'I cannot count these notes. Please spread them out flat and start again.',
  busy: 'Still counting, please wait.',
  cameraNeeded: 'This app needs the camera to count your money. Tap the screen to allow it.',
  listening: 'Listening.',
  tooShort: 'Hold the screen while you speak, then let go.',
  micNeeded: 'To ask by voice, allow the microphone. You can still tap to count.',
  heardFailed: "Sorry, I couldn't hear that. Please try again.",
  greeting: "Hi, I'm Birr. Put your notes flat on a table and tell me what you need, like count my money.",
  chooseLanguage: 'Tap the top half for English, or the bottom half for Amharic.',
  holdStill: 'Hold still, counting.',
  thinking: 'One moment.',
  languageChosen: 'Okay, I will speak this language now.',
};

let installed: Set<string> | null = null;
const phrases: Partial<Record<Lang, Phrases>> = {};
const phrasesLoading: Partial<Record<Lang, Promise<unknown>>> = {};
let player: AudioPlayer | null = null;
let clipSeq = 0; // bumped by every new clip and by stopSpeaking(): older clip work gives up
let clipPending = false; // a clip was asked for and has not started (or failed) yet
let beforeClip: (() => Promise<void>) | null = null;
const audioLog: string[] = [];

/** Remember a clip outcome (logcat, and the next /assist trace). */
function note(line: string, warn = false): void {
  if (warn) console.warn(`[birr] ${line}`);
  else console.log(`[birr] ${line}`);
  audioLog.push(line.slice(0, 160));
  if (audioLog.length > 8) audioLog.shift();
}

/** The last clip outcomes, sent with /assist so the backend trace shows what the phone did. */
export function recentAudioLog(): string[] {
  return [...audioLog];
}

/** Run before every clip (App: throw away a hands-free take that has heard nothing yet). */
export function setBeforeClip(fn: (() => Promise<void>) | null): void {
  beforeClip = fn;
}

/** Which of our languages have a voice on this phone. */
export async function loadVoices(): Promise<Set<Lang>> {
  try {
    const voices = await Speech.getAvailableVoicesAsync();
    installed = new Set(voices.map((v) => v.language.toLowerCase().slice(0, 2)));
  } catch (e) {
    console.warn('[birr] voice list failed', e);
    installed = new Set(['en']);
  }
  return new Set((Object.keys(LOCALE) as Lang[]).filter((l) => l === 'en' || installed!.has(l)));
}

export function setPhrases(lang: Lang, p: Phrases): void {
  phrases[lang] = p;
}

/** GET /phrases for `lang` is on its way: prompts wait for it (a while) instead of English. */
export function trackPhrases(lang: Lang, loading: Promise<unknown>): void {
  phrasesLoading[lang] = loading;
  loading.finally(() => {
    if (phrasesLoading[lang] === loading) delete phrasesLoading[lang];
  });
}

/** Pick the text and locale to speak: the user's language if both the text and a voice exist. */
export function pickSpeech(speech: SpeechText, lang: Lang): { text: string; locale: string } {
  const hasVoice = lang === 'en' || (installed?.has(lang) ?? false);
  if (speech[lang] && hasVoice) return { text: speech[lang]!, locale: LOCALE[lang] };
  return { text: speech.en ?? '', locale: LOCALE.en };
}

/** True while the app is saying something (text-to-speech, a clip, or a clip about to start). */
export async function isAppSpeaking(): Promise<boolean> {
  if (clipPending) return true;
  try {
    if (player?.playing) return true;
  } catch {
    // no player yet, or it was released
  }
  try {
    return await Speech.isSpeakingAsync();
  } catch {
    return false;
  }
}

/** Resolve once the app has been quiet for two checks in a row (or after `capMs`). */
export async function whenQuiet(capMs = 30_000): Promise<void> {
  const until = Date.now() + capMs;
  let quiet = 0;
  while (quiet < 2 && Date.now() < until) {
    quiet = (await isAppSpeaking()) ? 0 : quiet + 1;
    if (quiet < 2) await sleep(200);
  }
}

/** Stop whatever is being said: text-to-speech and clips (also one still being fetched). */
export function stopSpeaking(): void {
  Speech.stop();
  clipSeq += 1;
  clipPending = false;
  try {
    player?.pause();
  } catch {
    // nothing was playing
  }
}

/** Interrupt anything queued and say this now. */
export function say(text: string, locale = LOCALE.en): void {
  stopSpeaking();
  if (text) Speech.speak(text, { language: locale, rate: 0.95 });
}

/** Say this now, then call `then` when it has been said (or could not be). */
export function sayThen(text: string, locale: string, then: () => void): void {
  stopSpeaking();
  let called = false;
  const once = () => {
    if (!called) {
      called = true;
      then();
    }
  };
  Speech.speak(text, { language: locale, rate: 0.95, onDone: once, onStopped: once, onError: once });
}

/** Add to the queue without interrupting (used for the waiting cue). */
export function sayQueued(text: string, locale = LOCALE.en): void {
  Speech.speak(text, { language: locale, rate: 0.95 });
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ---- clip files

const clipDir = Platform.OS === 'web' ? null : new Directory(Paths.cache, 'clips');
const downloads = new Map<string, Promise<string>>();

function clipFile(remote: string): File | null {
  if (!clipDir) return null;
  // The clip id changes whenever the text or voice changes, so a kept file never goes stale.
  const id = remote.split('?')[0].split('/').pop() || 'clip';
  return new File(clipDir, `${id.replace(/[^A-Za-z0-9_-]/g, '')}.wav`);
}

/**
 * A local file for this clip: downloaded once (to a .part file, renamed when complete, so a
 * half-written file is never played), shared by everyone asking at the same time. Resolves to
 * the server link when the download fails or takes longer than `timeoutMs`.
 */
export function cacheClip(remote: string, timeoutMs = CLIP_DOWNLOAD_MS): Promise<string> {
  if (!/^https?:/.test(remote)) return Promise.resolve(remote);
  const file = clipFile(remote);
  if (!file) return Promise.resolve(remote);
  try {
    if (file.exists && (file.size ?? 0) > 44) return Promise.resolve(file.uri);
  } catch {
    // fall through to a download
  }
  let job = downloads.get(file.uri);
  if (!job) {
    job = (async () => {
      const started = Date.now();
      const part = new File(clipDir!, `${file.name}.part`);
      try {
        clipDir!.create({ intermediates: true, idempotent: true });
        if (part.exists) part.delete();
        await File.downloadFileAsync(remote, part, { idempotent: true });
        await part.move(file, { overwrite: true });
        console.log(`[birr] clip saved ${file.name} (${file.size ?? '?'} B, ${Date.now() - started} ms)`);
        return file.uri;
      } catch (e) {
        console.warn('[birr] clip download failed', remote, e);
        try {
          if (part.exists) part.delete();
        } catch {
          // nothing to clean up
        }
        return remote;
      } finally {
        downloads.delete(file.uri);
      }
    })();
    downloads.set(file.uri, job);
  }
  return Promise.race([job, sleep(timeoutMs).then(() => remote)]);
}

function forgetClipFile(uri: string): void {
  if (!uri.startsWith('file:')) return;
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    // keep going: the retry streams from the server
  }
}

// ---- playing clips

async function audioForPlayback(): Promise<void> {
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
      shouldRouteThroughEarpiece: false,
      allowsRecording: false,
      shouldPlayInBackground: false,
      interruptionMode: 'mixWithOthers', // no audio focus request: nothing can refuse the clip
    });
  } catch (e) {
    console.warn('[birr] audio mode for playback failed', e);
  }
}

function releasePlayer(): void {
  const p = player;
  player = null;
  if (!p) return;
  try {
    p.pause();
  } catch {
    // already stopped
  }
  try {
    p.remove();
  } catch {
    // already released
  }
}

type ClipResult = { ok: true; ms: number } | { ok: false; why: string } | { ok: false; cancelled: true };

/** One try: a fresh player for `src`; resolves once it plays, errors, or does not start in time. */
async function startClip(src: string, seq: number): Promise<ClipResult> {
  releasePlayer();
  const t0 = Date.now();
  let started = false;
  let error: string | null = null;
  let p: AudioPlayer;
  try {
    p = createAudioPlayer({ uri: src }, { updateInterval: 100 });
  } catch (e) {
    return { ok: false, why: `player: ${String(e)}` };
  }
  player = p;
  p.addListener('playbackStatusUpdate', (status) => {
    const s = status as typeof status & { error?: string };
    if (s.error) error = String(s.error);
    if (s.playing || s.didJustFinish || (s.currentTime ?? 0) > 0) started = true;
  });
  try {
    p.play();
  } catch (e) {
    error = `play: ${String(e)}`;
  }
  const limit = /^https?:/.test(src) ? CLIP_STREAM_START_MS : CLIP_START_MS;
  while (!started && !error && Date.now() - t0 < limit) {
    await sleep(100);
    if (seq !== clipSeq) return { ok: false, cancelled: true };
    try {
      if (p.playing || p.currentTime > 0) started = true;
    } catch {
      // released under us
    }
  }
  if (started) return { ok: true, ms: Date.now() - t0 };
  if (player === p) releasePlayer();
  return { ok: false, why: error ? `error: ${error}` : `not playing after ${limit} ms` };
}

/**
 * Play a clip (a URL or a local file). Downloads it first, sets the audio mode for playback,
 * and tries a fresh player once more if it does not start. If both tries fail, `fallback`
 * speaks the text instead.
 */
export function playClip(uri: string, fallback: () => void): void {
  stopSpeaking();
  const seq = ++clipSeq;
  clipPending = true;
  const asked = Date.now();
  void (async () => {
    try {
      if (beforeClip) {
        try {
          await beforeClip();
        } catch (e) {
          console.warn('[birr] before-clip hook failed', e);
        }
      }
      let src = await cacheClip(uri);
      if (seq !== clipSeq) return;
      for (let attempt = 1; attempt <= 2; attempt++) {
        await audioForPlayback();
        if (seq !== clipSeq) return;
        const result = await startClip(src, seq);
        if ('cancelled' in result) return;
        if (result.ok) {
          note(`clip started after ${Date.now() - asked} ms (${src.startsWith('file:') ? 'file' : 'stream'}${attempt > 1 ? ', retry' : ''})`);
          return;
        }
        note(`clip did not start (try ${attempt}, ${src.startsWith('file:') ? 'file' : 'stream'}): ${result.why}`, true);
        if (src.startsWith('file:') && /^https?:/.test(uri)) {
          forgetClipFile(src); // a bad cached file: the retry streams it from the server
          src = uri;
        }
      }
      note('clip failed twice, speaking instead', true);
      if (seq === clipSeq) {
        clipPending = false;
        fallback();
      }
    } finally {
      if (seq === clipSeq) clipPending = false;
    }
  })();
}

/** The text of one of the app's prompts in `lang` (English until the backend translated it). */
export function promptText(key: PhraseKey, lang: Lang): string {
  return phrases[lang]?.[key]?.text ?? PROMPTS[key];
}

/**
 * Speak one of the app's prompts in `lang`: its clip if there is one, else a phone voice.
 * `english` is what to say when there is no clip and no voice (default: the English prompt).
 * While GET /phrases is still on its way, waits for it (up to 8 s) instead of speaking English.
 */
export function sayPrompt(key: PhraseKey, lang: Lang, queued = false, english = PROMPTS[key]): void {
  if (lang !== 'en' && !phrases[lang] && phrasesLoading[lang] && !queued) {
    stopSpeaking();
    const seq = ++clipSeq;
    clipPending = true;
    void Promise.race([phrasesLoading[lang]!.catch(() => undefined), sleep(PHRASES_WAIT_MS)]).then(() => {
      if (seq !== clipSeq) return;
      clipPending = false;
      if (!phrases[lang]) console.warn(`[birr] phrases for ${lang} not here yet, saying '${key}' in English`);
      sayPrompt(key, lang, queued, english);
    });
    return;
  }
  const phrase = lang === 'en' ? undefined : phrases[lang]?.[key];
  if (phrase?.audio) {
    playClip(phrase.audio, () => say(english));
    return;
  }
  const { text, locale } = phrase ? pickSpeech({ en: english, [lang]: phrase.text }, lang) : { text: english, locale: LOCALE.en };
  if (queued) sayQueued(text, locale);
  else say(text, locale);
}

/**
 * Speak a backend answer and return the text to show. Uses the answer's clip when there is one,
 * else a phone voice for the language, else English. `translated` is false when the backend
 * flagged speech_todo (its `speech[lang]` is then English text).
 */
export function speakAnswer(speech: SpeechText, lang: Lang, audio?: string, translated = true): string {
  const use = translated ? lang : 'en';
  const shown = speech[use] ?? speech.en ?? '';
  const fallback = () => {
    const { text, locale } = pickSpeech(speech, use);
    say(text, locale);
  };
  if (use !== 'en' && audio) playClip(audio.startsWith('/') ? `${API_URL}${audio}` : audio, fallback);
  else fallback();
  return shown;
}
