// Canned /scan and /intent answers so the app can be tried before the backend is deployed
// (EXPO_PUBLIC_API_URL empty or "mock"). Scans cycle: total, guide, rescan. A change scan answers
// with a change check. Voice questions cycle: count, change (paid 500, price 320), not understood.

import type { Lang, ScanRequest } from './types';
import type { ScanOutcome } from './scan';
import type { IntentOutcome } from './voiceApi';

let turn = 0;
let question = 0;

export async function mockIntent(lang: Lang): Promise<IntentOutcome> {
  await new Promise((resolve) => setTimeout(resolve, 1500));
  const pick = question++ % 3;
  if (pick === 0) {
    const speech = { en: 'Spread your notes, hold the phone over them and tap the screen.' };
    return { kind: 'ok', body: { intent: 'count', next: 'scan', lang, paid: null, price: null, speech } };
  }
  if (pick === 1) {
    const en =
      'You paid 500 birr for 320 birr. Your change should be 180 birr. Spread it out, hold the phone over it and tap the screen.';
    return { kind: 'ok', body: { intent: 'change', next: 'scan', lang, paid: 500, price: 320, speech: { en } } };
  }
  const en = 'Sorry, I did not understand. Ask how much money you have, or say what you paid and the price to check your change.';
  return { kind: 'ok', body: { intent: 'unknown', next: 'ask', lang, paid: null, price: null, speech: { en } } };
}

export async function mockScan(req: ScanRequest): Promise<ScanOutcome> {
  await new Promise((resolve) => setTimeout(resolve, 3000));
  if (req.intent === 'change' && req.paid != null && req.price != null) {
    const expected = req.paid - req.price;
    return {
      kind: 'ok',
      body: {
        outcome: 'total',
        total: 180,
        change: { expected, counted: 180, difference: 180 - expected },
        notes: [
          { denomination: 100, confidence: null, box: null, status: 'read' },
          { denomination: 50, confidence: null, box: null, status: 'read' },
          { denomination: 10, confidence: null, box: null, status: 'read' },
          { denomination: 10, confidence: null, box: null, status: 'read' },
          { denomination: 10, confidence: null, box: null, status: 'read' },
        ],
        hint: null,
        speech: {
          en:
            expected === 180
              ? 'You got 180 birr change. You should get 180 birr. Your change is correct.'
              : `You got 180 birr change. You should get ${expected} birr.`,
        },
      },
    };
  }
  const pick = turn++ % 3;
  if (pick === 0) {
    return {
      kind: 'ok',
      body: {
        outcome: 'total',
        total: 350,
        change: null,
        notes: [
          { denomination: 200, confidence: null, box: null, status: 'read' },
          { denomination: 100, confidence: null, box: null, status: 'read' },
          { denomination: 50, confidence: null, box: null, status: 'read' },
        ],
        hint: null,
        speech: { en: 'You have 350 birr: one 200, one 100 and one 50.' },
      },
    };
  }
  if (pick === 1) {
    return {
      kind: 'ok',
      body: {
        outcome: 'guide',
        total: null,
        change: null,
        notes: [],
        hint: { note_index: null, position: 'far left', covered_by: 0, action: 'slide_out' },
        speech: { en: 'One note is covered, at the far left. Slide it out so I can see all of it, then tap again.' },
      },
    };
  }
  return {
    kind: 'ok',
    body: {
      outcome: 'rescan',
      total: null,
      change: null,
      notes: [],
      hint: null,
      speech: { en: `I could not read every note. Please spread them a little and tap again. Try ${req.attempt + 1}.` },
    },
  };
}
