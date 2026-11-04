// The voice assistant's calls to our backend (docs/api.md sections 7 and 8).
//   POST /assist  one spoken turn -> what to do and say (Omnilingual ASR + Muse on the backend)
//   POST /frame   a small camera frame -> is it good enough to count, and if not, what to fix
// Both resolve (never throw), so the screen always has something to say. `missing` means the
// backend is older than the assistant (404): the app then falls back to /intent and plain taps.

import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

import { API_URL, filePart, postForm, usingMock } from './scan';
import type { AssistResponse, AssistState, FrameResponse, Lang, ScanError } from './types';

export type Outcome<T> =
  | { kind: 'ok'; body: T }
  | { kind: 'error'; body: ScanError }
  | { kind: 'missing' }
  | { kind: 'timeout' }
  | { kind: 'network' };

export const FRAME_SIDE = 640;

async function post<T>(path: string, form: FormData, timeoutMs: number, label: string): Promise<Outcome<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const { status, text } = await postForm(`${API_URL}${path}`, form, controller.signal);
    if (status === 404 || status === 405) {
      console.log(`[birr] POST ${path} -> ${status} (backend has no ${path})`);
      return { kind: 'missing' };
    }
    let body: unknown = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = null; // a proxy's HTML error page, or a cut-off answer
    }
    console.log(`[birr] POST ${path} ${label} -> ${status}${status === 200 && body ? ` ${summary(body)}` : ''}`);
    if (body && status === 200) return { kind: 'ok', body: body as T };
    if (body) return { kind: 'error', body: body as ScanError };
    // A 5xx without our JSON (gateway/proxy): the server side failed, not the phone's network.
    if (status >= 500) return { kind: 'error', body: { error: 'upstream_error', speech: {} } };
    return { kind: 'network' };
  } catch (e) {
    console.warn(`[birr] ${path} failed`, controller.signal.aborted ? '(timeout)' : '', e);
    return controller.signal.aborted ? { kind: 'timeout' } : { kind: 'network' };
  } finally {
    clearTimeout(timer);
  }
}

function summary(body: Partial<AssistResponse & FrameResponse>): string {
  if (body.action) return `action=${body.action} lang=${body.lang} by=${body.decided_by ?? '?'}`;
  if (body.status) return `status=${body.status}${body.side ? `:${body.side}` : ''}`;
  return '';
}

/** One spoken turn (a recording), or a typed one. */
export async function assist(
  input: { uri: string } | { text: string },
  lang: Lang,
  sessionId: string,
  state: AssistState,
  timeoutMs: number,
): Promise<Outcome<AssistResponse>> {
  if (usingMock) {
    const body: AssistResponse = {
      action: 'scan', intent: 'count', lang, paid: null, price: null, needs: null, heard: true,
      speech: { en: 'Okay. Hold the phone over your notes. I will tell you when it looks good.' },
    }; // prettier-ignore
    return { kind: 'ok', body };
  }
  const form = new FormData();
  if ('uri' in input) {
    // Phones record AAC in .m4a; browsers record WebM. The backend takes both.
    const part = await filePart(input.uri, 'turn.m4a', 'audio/mp4');
    form.append('audio', part, part.type?.includes('webm') ? 'turn.webm' : 'turn.m4a');
  } else {
    form.append('text', input.text);
  }
  form.append('lang', lang);
  form.append('session_id', sessionId);
  form.append('state', JSON.stringify(state));
  return post<AssistResponse>('/assist', form, timeoutMs, `lang=${lang}`);
}

/** A small, low-quality copy of a camera frame for /frame (orientation baked in, no EXIF). */
export async function smallFrame(uri: string, width: number, height: number): Promise<string> {
  const ctx = ImageManipulator.manipulate(uri);
  ctx.resize(width >= height ? { width: FRAME_SIDE, height: null } : { width: null, height: FRAME_SIDE });
  const image = await ctx.renderAsync();
  return (await image.saveAsync({ format: SaveFormat.JPEG, compress: 0.4 })).uri;
}

export async function checkFrame(uri: string, lang: Lang, timeoutMs: number): Promise<Outcome<FrameResponse>> {
  if (usingMock) return { kind: 'ok', body: { status: 'ok', side: null, ready: true, speech: { en: 'Good. Hold still.' } } };
  const form = new FormData();
  form.append('image', await filePart(uri, 'frame.jpg', 'image/jpeg'), 'frame.jpg');
  form.append('lang', lang);
  return post<FrameResponse>('/frame', form, timeoutMs, `lang=${lang}`);
}
