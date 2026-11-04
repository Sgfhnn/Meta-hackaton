// Live camera guidance: while the camera is open, check a small frame about every 1.2 s with
// POST /frame and say what to fix ("too dark", "move closer", "cut off on the left"). Two good
// frames in a row mean "take the real photo now". The loop itself is plain code with no React,
// so App.tsx decides what each outcome means.

import type { FrameResponse } from './types';
import type { Outcome } from './assistApi';

export type GuideEnd = 'ready' | 'tapped' | 'timeout' | 'cancelled' | 'unavailable';

export type GuideOptions = {
  /** Take a small frame and return its file uri. */
  takeFrame: () => Promise<string>;
  check: (uri: string) => Promise<Outcome<FrameResponse>>;
  /** Say a hint (already debounced here). */
  hint: (frame: FrameResponse) => void;
  /** A good frame: a light haptic tick. */
  good: () => void;
  /** 'tapped' (take the photo now), 'cancelled', or null to go on. */
  stop: () => 'tapped' | 'cancelled' | null;
  intervalMs?: number;
  capMs?: number; // after this, take the photo anyway
  okNeeded?: number;
  repeatMs?: number; // the same hint is not said again within this
  startDelayMs?: number; // let the "hold the phone over your notes" line finish first
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export async function guide(o: GuideOptions): Promise<GuideEnd> {
  const interval = o.intervalMs ?? 1200;
  const cap = o.capMs ?? 30_000;
  const okNeeded = o.okNeeded ?? 2;
  const repeat = o.repeatMs ?? 4000;
  const started = Date.now();
  let okStreak = 0;
  let failures = 0;
  let lastKey = '';
  let lastAt = 0;
  const waitUntil = started + (o.startDelayMs ?? 0);
  while (Date.now() < waitUntil) {
    const s = o.stop();
    if (s) return s;
    await sleep(100);
  }
  for (;;) {
    const s = o.stop();
    if (s) return s;
    if (Date.now() - started > cap) return 'timeout';
    const t0 = Date.now();
    let result: Outcome<FrameResponse>;
    try {
      result = await o.check(await o.takeFrame());
    } catch (e) {
      console.warn('[birr] guidance frame failed', e);
      result = { kind: 'network' };
    }
    const after = o.stop();
    if (after) return after;
    if (result.kind === 'missing') return 'unavailable';
    if (result.kind !== 'ok') {
      failures += 1;
      if (failures >= 3) return 'unavailable';
    } else {
      failures = 0;
      const frame = result.body;
      const key = `${frame.status}:${frame.side ?? ''}`;
      if (frame.ready) {
        okStreak += 1;
        o.good();
        if (okStreak >= okNeeded) return 'ready';
      } else {
        okStreak = 0;
      }
      const now = Date.now();
      if (key !== lastKey || now - lastAt >= repeat) {
        o.hint(frame);
        lastKey = key;
        lastAt = now;
      }
    }
    await sleep(Math.max(0, interval - (Date.now() - t0)));
  }
}
