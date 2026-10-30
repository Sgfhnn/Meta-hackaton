// Canned /scan answers so the app can be tried before the backend is deployed
// (EXPO_PUBLIC_API_URL empty or "mock"). They cycle: total, guide, rescan.

import type { ScanRequest } from './types';
import type { ScanOutcome } from './scan';

let turn = 0;

export async function mockScan(req: ScanRequest): Promise<ScanOutcome> {
  await new Promise((resolve) => setTimeout(resolve, 3000));
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
