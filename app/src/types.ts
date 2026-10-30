// Response shapes from docs/api.md (POST /scan). Keep in sync with the contract.

export type Lang = 'en' | 'am' | 'om';

export type Speech = Partial<Record<Lang, string>>;

export type Note = {
  denomination: 5 | 10 | 50 | 100 | 200 | null;
  confidence: number | null;
  box: [number, number, number, number] | null;
  status: 'read' | 'partial' | 'unclear';
};

export type Hint = {
  note_index: number | null;
  position: string;
  relation?: 'under_top' | 'next_to';
  covered_by: number | null;
  action: 'slide_out' | 'lay_flat' | 'move_closer' | 'more_light';
};

// Spoken text in every answer. speech_audio links a ready clip (GET /speak/{id}) in the user's
// language; speech_todo means the backend had no checked translation, so speech carries English.
export type Spoken = {
  speech: Speech;
  speech_audio?: string;
  speech_todo?: string;
};

export type ScanResponse = Spoken & {
  outcome: 'total' | 'guide' | 'rescan';
  total: number | null;
  change: { expected: number; counted: number; difference: number } | null;
  notes: Note[];
  hint: Hint | null;
  trace_id?: string;
  timing_ms?: Record<string, number | null>;
};

export type ScanError = Spoken & {
  error: string;
  trace_id?: string | null;
};

export type ScanRequest = {
  lang: Lang;
  attempt: number;
  maxAttempts: number;
  intent: 'count' | 'change';
  paid?: number;
  price?: number;
};

// POST /intent: what the user asked by voice, and what the app does next.
export type IntentResponse = Spoken & {
  intent: 'count' | 'change' | 'unknown';
  next: 'scan' | 'ask' | 'done';
  lang: Lang;
  paid: number | null;
  price: number | null;
  trace_id?: string;
};

// GET /phrases: the app's own prompts (voice.ts PROMPTS keys) in Amharic or Oromo.
export type PhraseKey =
  | 'counting'
  | 'stillCounting'
  | 'failed'
  | 'noNetwork'
  | 'giveUp'
  | 'busy'
  | 'cameraNeeded'
  | 'listening'
  | 'tooShort'
  | 'micNeeded'
  | 'heardFailed';

export type Phrases = Partial<Record<PhraseKey, { text: string; audio: string | null }>>;

// POST /scan starts a job (202); GET /scan/{job_id} reports on it (docs/api.md, scan v2).
export type JobStarted = {
  job_id: string;
  status: 'pending';
  poll_url?: string;
  poll_after_ms?: number;
};

export type JobStatus = Partial<Spoken> & {
  job_id: string;
  status: 'pending' | 'done' | 'error';
  result: ScanResponse | null;
  poll_after_ms?: number;
  error?: string;
};
