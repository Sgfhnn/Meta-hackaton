// Photo prep and the POST /scan call. The app holds no model keys: it only talks to our backend.

import { File, UploadType } from 'expo-file-system';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { Platform } from 'react-native';

import { mockScan } from './mock';
import type { ScanError, ScanRequest, ScanResponse } from './types';

const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');

export const usingMock = API_URL === '' || API_URL === 'mock';

const MAX_SIDE = 1280; // the backend resizes again (IMAGE_MAX_PX); this just keeps uploads small

/** Resize and re-encode as JPEG. Re-encoding drops EXIF (including GPS), as the contract requires. */
export async function preparePhoto(uri: string, width: number, height: number): Promise<string> {
  const ctx = ImageManipulator.manipulate(uri);
  if (Math.max(width, height) > MAX_SIDE) {
    ctx.resize(width >= height ? { width: MAX_SIDE, height: null } : { width: null, height: MAX_SIDE });
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
  return {
    intent: 'count',
    lang: req.lang,
    attempt: String(req.attempt),
    max_attempts: String(req.maxAttempts),
    ...(req.fast ? { fast: '1' } : {}),
  };
}

function parse(status: number, text: string): ScanOutcome {
  try {
    const body = JSON.parse(text);
    return status === 200 ? { kind: 'ok', body } : { kind: 'error', body };
  } catch {
    return { kind: 'network' };
  }
}

/** Send one photo. Resolves (never throws) so the screen always has something to say. */
export async function scan(photoUri: string, req: ScanRequest, timeoutMs: number): Promise<ScanOutcome> {
  if (usingMock) return mockScan(req);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    if (Platform.OS === 'web') {
      // expo-file-system has no web support; the web preview posts a Blob instead.
      const form = new FormData();
      form.append('image', await (await fetch(photoUri)).blob(), 'scan.jpg');
      for (const [k, v] of Object.entries(formFields(req))) form.append(k, v);
      const res = await fetch(`${API_URL}/scan`, { method: 'POST', body: form, signal: controller.signal });
      return parse(res.status, await res.text());
    }
    const res = await new File(photoUri).upload(`${API_URL}/scan`, {
      uploadType: UploadType.MULTIPART,
      fieldName: 'image',
      mimeType: 'image/jpeg',
      parameters: formFields(req),
      sessionType: 'foreground',
      signal: controller.signal,
    });
    return parse(res.status, res.body);
  } catch {
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}
