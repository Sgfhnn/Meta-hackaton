// Voice calls to our backend (docs/api.md). The models run on the backend; the app holds no keys.
//   POST /intent   the user's spoken question -> what to do next
//   GET  /phrases  the app's own prompts in Amharic or Oromo, with clips kept on the phone
//   GET  /health   whether the backend answers in Amharic and Oromo

import { mockIntent } from './mock';
import { cacheClip } from './voice';
import { API_URL, filePart, postForm, usingMock } from './scan';
import type { IntentResponse, Lang, Phrases, ScanError } from './types';

export type IntentOutcome =
  | { kind: 'ok'; body: IntentResponse }
  | { kind: 'error'; body: ScanError }
  | { kind: 'timeout' }
  | { kind: 'network' };

/** Send a recorded question. Resolves (never throws) so the screen always has something to say. */
export async function askIntent(audioUri: string, lang: Lang, timeoutMs: number): Promise<IntentOutcome> {
  if (usingMock) return mockIntent(lang);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const form = new FormData();
    // Phones record AAC in .m4a (RecordingPresets.HIGH_QUALITY); browsers record WebM. The backend takes both.
    const part = await filePart(audioUri, 'question.m4a', 'audio/mp4');
    form.append('audio', part, part.type?.includes('webm') ? 'question.webm' : 'question.m4a');
    form.append('lang', lang);
    const { status, text } = await postForm(`${API_URL}/intent`, form, controller.signal);
    console.log(`[birr] POST /intent lang=${lang} -> ${status}`);
    const body = JSON.parse(text);
    return status === 200 ? { kind: 'ok', body: body as IntentResponse } : { kind: 'error', body: body as ScanError };
  } catch (e) {
    console.warn('[birr] intent failed', controller.signal.aborted ? '(timeout)' : '', e);
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * True when the backend answers in Amharic and Oromo, so those languages are worth offering.
 * Tries a few times: right after the app opens the network is sometimes not up yet.
 */
export async function backendTranslates(tries = 3): Promise<boolean> {
  if (usingMock) return false;
  for (let i = 1; i <= tries; i++) {
    try {
      const res = await fetch(`${API_URL}/health`);
      const body = (await res.json()) as { voice?: { translates?: boolean; gemini?: boolean } };
      // `translates` (templates, always on); older backends only said `gemini`.
      return body.voice?.translates === true || body.voice?.gemini === true;
    } catch (e) {
      console.warn(`[birr] health check failed (try ${i} of ${tries})`, e);
      if (i < tries) await new Promise((r) => setTimeout(r, 3000));
    }
  }
  return false;
}

/**
 * The app's prompts in `lang`. Resolves as soon as the texts arrive, with clip links to the
 * server; the clips then download one by one in the background (voice.ts cacheClip) and each
 * link becomes a local file once it is there, so "I cannot reach the server" still plays when
 * the network is down later. One request per language at a time (the language screen and the
 * chosen language used to fetch, and write, the same files at once).
 */
const phraseRequests: Partial<Record<Lang, Promise<Phrases>>> = {};

export function fetchPhrases(lang: Lang): Promise<Phrases> {
  if (usingMock || lang === 'en') return Promise.resolve({});
  const running = phraseRequests[lang];
  if (running) return running;
  const request = loadPhrases(lang);
  phraseRequests[lang] = request;
  request.then((p) => {
    // Keep a good answer for this launch; ask again next time only if it failed.
    if (Object.keys(p).length === 0 && phraseRequests[lang] === request) delete phraseRequests[lang];
  });
  return request;
}

async function loadPhrases(lang: Lang): Promise<Phrases> {
  let phrases: Phrases;
  try {
    const res = await fetch(`${API_URL}/phrases?lang=${lang}`);
    if (!res.ok) return {};
    phrases = ((await res.json()) as { phrases?: Phrases }).phrases ?? {};
  } catch (e) {
    console.warn('[birr] phrases fetch failed', e);
    return {};
  }
  for (const phrase of Object.values(phrases)) {
    if (phrase?.audio?.startsWith('/')) phrase.audio = `${API_URL}${phrase.audio}`;
  }
  void (async () => {
    // The ones said first go first.
    const order = ['chooseLanguage', 'languageChosen', 'greeting', 'listening', 'heardFailed', 'noNetwork'];
    const entries = Object.entries(phrases).sort(
      ([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99),
    );
    let saved = 0;
    for (const [, phrase] of entries) {
      if (!phrase?.audio || !/^https?:/.test(phrase.audio)) continue;
      const local = await cacheClip(phrase.audio, 60_000);
      if (local.startsWith('file:')) {
        phrase.audio = local;
        saved += 1;
      }
    }
    console.log(`[birr] phrases ${lang}: ${saved} clips on the phone`);
  })();
  return phrases;
}
