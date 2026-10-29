// Spoken output through the phone's text-to-speech. The backend writes the result text
// (docs/api.md: the app speaks `speech` word for word); the short prompts below are the app's own.

import * as Speech from 'expo-speech';

import type { Lang, Speech as SpeechText } from './types';

const LOCALE: Record<Lang, string> = { en: 'en-US', am: 'am-ET', om: 'om-ET' };

// App-side prompts. English only for now: Amharic and Oromo come with the Gemini voice work,
// so no translation is guessed here.
export const PROMPTS = {
  counting: 'Counting.',
  stillCounting: 'Still counting.',
  slowRetry: 'This is taking long. Trying a quicker count.',
  failed: 'Sorry, I could not count that. Please tap to try again.',
  noNetwork: 'I cannot reach the server. Check the internet connection and tap to try again.',
  giveUp: 'I cannot count these notes. Please spread them out flat and start again.',
  busy: 'Still counting, please wait.',
  cameraNeeded: 'This app needs the camera to count your money. Tap the screen to allow it.',
};

let installed: Set<string> | null = null;

/** Which of our languages have a voice on this phone. */
export async function loadVoices(): Promise<Set<Lang>> {
  try {
    const voices = await Speech.getAvailableVoicesAsync();
    installed = new Set(voices.map((v) => v.language.toLowerCase().slice(0, 2)));
  } catch {
    installed = new Set(['en']);
  }
  return new Set((Object.keys(LOCALE) as Lang[]).filter((l) => l === 'en' || installed!.has(l)));
}

/** Pick the text and locale to speak: the user's language if both the text and a voice exist. */
export function pickSpeech(speech: SpeechText, lang: Lang): { text: string; locale: string } {
  const hasVoice = lang === 'en' || (installed?.has(lang) ?? false);
  if (speech[lang] && hasVoice) return { text: speech[lang]!, locale: LOCALE[lang] };
  return { text: speech.en ?? '', locale: LOCALE.en };
}

/** Interrupt anything queued and say this now. */
export function say(text: string, locale = LOCALE.en): void {
  Speech.stop();
  if (text) Speech.speak(text, { language: locale, rate: 0.95 });
}

/** Add to the queue without interrupting (used for the waiting cue). */
export function sayQueued(text: string): void {
  Speech.speak(text, { language: LOCALE.en, rate: 0.95 });
}
