// Photo prep and the /scan calls. The app holds no model keys: it only talks to our backend.
//
// Scan v2 (docs/api.md): POST /scan answers 202 with a job_id, then GET /scan/{job_id} is polled
// until the job is done. A backend that answers POST with 200 and the result directly (the older
// synchronous /scan, or wait=true) is handled too.

import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { Platform } from 'react-native';

import { mockScan } from './mock';
import { UPLOAD_MAX_SIDE } from './pictureSize';
import type { JobStarted, JobStatus, ScanError, ScanRequest, ScanResponse } from './types';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');

export const usingMock = API_URL === '' || API_URL === 'mock';

const DEFAULT_POLL_MS = 1500;

/**
 * Cap the long side at 2048 px (never upscale) and re-encode as JPEG. The backend reads notes at
 * 2048 px and shrinks its own copy for SAM. Re-encoding drops EXIF (including GPS), as the contract requires.
 */
export async function preparePhoto(uri: string, width: number, height: number): Promise<string> {
  const ctx = ImageManipulator.manipulate(uri);
  if (Math.max(width, height) > UPLOAD_MAX_SIDE) {
    ctx.resize(
      width >= height ? { width: UPLOAD_MAX_SIDE, height: null } : { width: null, height: UPLOAD_MAX_SIDE },
    );
  }
  const image = await ctx.renderAsync();
  const result = await image.saveAsync({ format: SaveFormat.JPEG, compress: 0.85 });
  return result.uri;
}

export type ScanOutcome =
  | { kind: 'ok'; body: ScanResponse }
  | { kind: 'error'; body: ScanError }
  | { kind: 'timeout' }
  | { kind: 'network' };

function formFields(req: ScanRequest): Record<string, string> {
  const fields: Record<string, string> = {
    intent: req.intent,
    lang: req.lang,
    attempt: String(req.attempt),
    max_attempts: String(req.maxAttempts),
  };
  if (req.intent === 'change' && req.paid != null && req.price != null) {
    fields.paid = String(req.paid);
    fields.price = String(req.price);
  }
  return fields;
}

async function upload(photoUri: string, req: ScanRequest, signal: AbortSignal) {
  if (Platform.OS === 'web') {
    // expo-file-system has no web support; the web preview posts a Blob instead.
    const form = new FormData();
    form.append('image', await (await fetch(photoUri)).blob(), 'scan.jpg');
    for (const [k, v] of Object.entries(formFields(req))) form.append(k, v);
    const res = await fetch(`${API_URL}/scan`, { method: 'POST', body: form, signal });
    return { status: res.status, text: await res.text() };
  }
  // React Native's fetch + FormData with a file uri works in Expo Go and in standalone APKs alike
  // (expo-file-system File.upload failed before reaching the server in the release APK).
  const form = new FormData();
  form.append('image', { uri: photoUri, name: 'scan.jpg', type: 'image/jpeg' } as unknown as Blob);
  for (const [k, v] of Object.entries(formFields(req))) form.append(k, v);
  const res = await fetch(`${API_URL}/scan`, { method: 'POST', body: form, signal });
  return { status: res.status, text: await res.text() };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new Error('aborted'));
    });
  });
}

/**
 * Send one photo and wait for the answer. Resolves (never throws) so the screen always has
 * something to say. The backend ends a slow scan itself (60 s, as a rescan answer); timeoutMs is
 * only a safety net for a lost connection.
 */
export async function scan(photoUri: string, req: ScanRequest, timeoutMs: number): Promise<ScanOutcome> {
  if (usingMock) return mockScan(req);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const started = await upload(photoUri, req, controller.signal);
    const body = JSON.parse(started.text);
    if (started.status === 200) return { kind: 'ok', body: body as ScanResponse };
    if (started.status !== 202) return { kind: 'error', body: body as ScanError };

    const job = body as JobStarted;
    let wait = job.poll_after_ms ?? DEFAULT_POLL_MS;
    for (;;) {
      await sleep(wait, controller.signal);
      const res = await fetch(`${API_URL}/scan/${encodeURIComponent(job.job_id)}`, {
        signal: controller.signal,
      });
      const status = (await res.json()) as JobStatus & ScanError;
      if (res.status !== 200) return { kind: 'error', body: status };
      if (status.status === 'done' && status.result) return { kind: 'ok', body: status.result };
      if (status.status === 'error') {
        const { speech = {}, speech_audio, speech_todo } = status;
        return { kind: 'error', body: { error: status.error ?? 'error', speech, speech_audio, speech_todo } };
      }
      wait = status.poll_after_ms ?? DEFAULT_POLL_MS;
    }
  } catch {
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}
