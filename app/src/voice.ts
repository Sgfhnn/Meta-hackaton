// Spoken output. The backend writes the answers (docs/api.md: the app speaks `speech` word for
// word); the short prompts below are the app's own. English goes through the phone's text-to-speech.
// Amharic and Oromo play as clips the backend made with Meta MMS-TTS.

import { createAudioPlayer, type AudioPlayer } from 'expo-audio';
import * as Speech from 'expo-speech';

import { API_URL } from './scan';
import type { Lang, PhraseKey, Phrases, Speech as SpeechText } from './types';

const LOCALE: Record<Lang, string> = { en: 'en-US', am: 'am-ET', om: 'om-ET' };
// A clip that has not started by then never will (no network): speak the text instead.
const CLIP_START_MS = 5000;

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
};

let installed: Set<string> | null = null;
const phrases: Partial<Record<Lang, Phrases>> = {};
let player: AudioPlayer | null = null;
let clipWatch: ReturnType<typeof setTimeout> | null = null;

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

/** Pick the text and locale to speak: the user's language if both the text and a voice exist. */
export function pickSpeech(speech: SpeechText, lang: Lang): { text: string; locale: string } {
  const hasVoice = lang === 'en' || (installed?.has(lang) ?? false);
  if (speech[lang] && hasVoice) return { text: speech[lang]!, locale: LOCALE[lang] };
  return { text: speech.en ?? '', locale: LOCALE.en };
}

/** Stop whatever is being said: text-to-speech and clips. */
export function stopSpeaking(): void {
  Speech.stop();
  if (clipWatch) clearTimeout(clipWatch);
  clipWatch = null;
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

/** Add to the queue without interrupting (used for the waiting cue). */
export function sayQueued(text: string, locale = LOCALE.en): void {
  Speech.speak(text, { language: locale, rate: 0.95 });
}

/** Play a clip (a URL or a local file). If it can't start, `fallback` speaks the text instead. */
export function playClip(uri: string, fallback: () => void): void {
  stopSpeaking();
  try {
    if (!player) player = createAudioPlayer(null);
    player.replace({ uri });
    player.play();
  } catch (e) {
    console.warn('[birr] clip failed', uri, e);
    fallback();
    return;
  }
  const p = player;
  clipWatch = setTimeout(() => {
    clipWatch = null;
    if (!p.playing && !p.isLoaded) {
      console.warn('[birr] clip did not start, speaking instead', uri);
      p.pause();
      fallback();
    }
  }, CLIP_START_MS);
}

/** The text of one of the app's prompts in `lang` (English until the backend translated it). */
export function promptText(key: PhraseKey, lang: Lang): string {
  return phrases[lang]?.[key]?.text ?? PROMPTS[key];
}

/** Speak one of the app's prompts in `lang`: its clip if there is one, else a phone voice. */
export function sayPrompt(key: PhraseKey, lang: Lang, queued = false): void {
  const phrase = lang === 'en' ? undefined : phrases[lang]?.[key];
  if (phrase?.audio) {
    playClip(phrase.audio, () => say(PROMPTS[key]));
    return;
  }
  const { text, locale } = phrase
    ? pickSpeech({ en: PROMPTS[key], [lang]: phrase.text }, lang)
    : { text: PROMPTS[key], locale: LOCALE.en };
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
