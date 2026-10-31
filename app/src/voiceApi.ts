// Voice calls to our backend (docs/api.md). The models run on the backend; the app holds no keys.
//   POST /intent   the user's spoken question -> what to do next
//   GET  /phrases  the app's own prompts in Amharic or Oromo, with clips kept on the phone
//   GET  /health   whether the backend answers in Amharic and Oromo

import { Directory, File, Paths, UploadType } from 'expo-file-system';
import { Platform } from 'react-native';

import { mockIntent } from './mock';
import { API_URL, usingMock } from './scan';
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
    let status: number;
    let text: string;
    if (Platform.OS === 'web') {
      // Browsers record WebM; the backend accepts it.
      const blob = await (await fetch(audioUri)).blob();
      const form = new FormData();
      form.append('audio', blob, blob.type.includes('webm') ? 'question.webm' : 'question.m4a');
      form.append('lang', lang);
      const res = await fetch(`${API_URL}/intent`, { method: 'POST', body: form, signal: controller.signal });
      status = res.status;
      text = await res.text();
    } else {
      const res = await new File(audioUri).upload(`${API_URL}/intent`, {
        uploadType: UploadType.MULTIPART,
        fieldName: 'audio',
        mimeType: 'audio/mp4', // AAC in .m4a (RecordingPresets.HIGH_QUALITY)
        parameters: { lang },
        sessionType: 'foreground',
        signal: controller.signal,
      });
      status = res.status;
      text = res.body;
    }
    const body = JSON.parse(text);
    return status === 200 ? { kind: 'ok', body: body as IntentResponse } : { kind: 'error', body: body as ScanError };
  } catch {
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}

/** True when the backend answers in Amharic and Oromo, so those languages are worth offering. */
export async function backendTranslates(): Promise<boolean> {
  if (usingMock) return false;
  try {
    const res = await fetch(`${API_URL}/health`);
    const body = (await res.json()) as { voice?: { translates?: boolean; gemini?: boolean } };
    // `translates` (templates, always on); older backends only said `gemini`.
    return body.voice?.translates === true || body.voice?.gemini === true;
  } catch {
    return false;
  }
}

/**
 * The app's prompts in `lang`. Clip links come back as full URLs, or as local files once
 * downloaded, so "I cannot reach the server" still plays when the network is down.
 */
export async function fetchPhrases(lang: Lang): Promise<Phrases> {
  if (usingMock || lang === 'en') return {};
  let phrases: Phrases;
  try {
    const res = await fetch(`${API_URL}/phrases?lang=${lang}`);
    if (!res.ok) return {};
    phrases = ((await res.json()) as { phrases?: Phrases }).phrases ?? {};
  } catch {
    return {};
  }
  const dir = Platform.OS === 'web' ? null : new Directory(Paths.cache, 'phrases');
  try {
    dir?.create({ intermediates: true, idempotent: true });
  } catch {
    // no cache folder: play the clips from the server instead
  }
  for (const phrase of Object.values(phrases)) {
    if (!phrase?.audio) continue;
    const remote = `${API_URL}${phrase.audio}`;
    phrase.audio = remote;
    if (!dir) continue;
    // The clip id changes whenever the text or voice changes, so a kept file never goes stale.
    const file = new File(dir, `${phrase.audio.split('/').pop()}.wav`);
    try {
      if (!file.exists) await File.downloadFileAsync(remote, file, { idempotent: true });
      phrase.audio = file.uri;
    } catch {
      // keep the server link
    }
  }
  return phrases;
}
