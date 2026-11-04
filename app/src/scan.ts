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

// Optional separate counting backend (the Vercel function, which never sleeps). It answers with
// wait=true, so there is no job to poll. Voice, guidance and clips stay on API_URL.
export const SCAN_URL = (process.env.EXPO_PUBLIC_SCAN_URL ?? '').replace(/\/+$/, '') || API_URL;
const scanWaits = SCAN_URL !== API_URL;

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

/**
 * POST a multipart form with XMLHttpRequest. On a phone, React Native's own networking sends file
 * parts given as { uri, name, type }. Not fetch: Expo SDK 58 replaces the global fetch with
 * expo/fetch, which rejects those parts ("Unsupported FormDataPart implementation"), and
 * expo-file-system's File.upload never reached the server in the release APK either.
 */
export function postForm(url: string, form: FormData, signal: AbortSignal): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    xhr.open('POST', url);
    xhr.onload = () => {
      signal.removeEventListener('abort', onAbort);
      resolve({ status: xhr.status, text: xhr.responseText });
    };
    xhr.onerror = () => {
      signal.removeEventListener('abort', onAbort);
      reject(new Error(`network error posting to ${url}`));
    };
    xhr.onabort = () => reject(new Error('aborted'));
    if (signal.aborted) {
      reject(new Error('aborted'));
      return;
    }
    signal.addEventListener('abort', onAbort);
    xhr.send(form);
  });
}

/** A file on the phone as a form part (web: the blob itself). */
export async function filePart(uri: string, name: string, type: string): Promise<Blob> {
  if (Platform.OS === 'web') return await (await fetch(uri)).blob();
  return { uri, name, type } as unknown as Blob;
}

async function upload(photoUri: string, req: ScanRequest, signal: AbortSignal) {
  const form = new FormData();
  form.append('image', await filePart(photoUri, 'scan.jpg', 'image/jpeg'), 'scan.jpg');
  for (const [k, v] of Object.entries(formFields(req))) form.append(k, v);
  if (scanWaits) form.append('wait', 'true');
  return postForm(`${SCAN_URL}/scan`, form, signal);
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
    console.log(`[birr] POST /scan -> ${started.status}`);
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
      console.log(`[birr] GET /scan/${job.job_id} -> ${res.status} ${status.status}`);
      if (res.status !== 200) return { kind: 'error', body: status };
      if (status.status === 'done' && status.result) return { kind: 'ok', body: status.result };
      if (status.status === 'error') {
        const { speech = {}, speech_audio, speech_todo } = status;
        return { kind: 'error', body: { error: status.error ?? 'error', speech, speech_audio, speech_todo } };
      }
      wait = status.poll_after_ms ?? DEFAULT_POLL_MS;
    }
  } catch (e) {
    console.warn('[birr] scan failed', controller.signal.aborted ? '(timeout)' : '', e);
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}
