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

export type ScanResponse = {
  outcome: 'total' | 'guide' | 'rescan';
  total: number | null;
  change: { expected: number; counted: number; difference: number } | null;
  notes: Note[];
  hint: Hint | null;
  speech: Speech;
  trace_id?: string;
  timing_ms?: Record<string, number | null>;
};

export type ScanError = {
  error: string;
  speech: Speech;
  trace_id?: string | null;
};

export type ScanRequest = {
  lang: Lang;
  attempt: number;
  maxAttempts: number;
};

// POST /scan starts a job (202); GET /scan/{job_id} reports on it (docs/api.md, scan v2).
export type JobStarted = {
  job_id: string;
  status: 'pending';
  poll_url?: string;
  poll_after_ms?: number;
};

export type JobStatus = {
  job_id: string;
  status: 'pending' | 'done' | 'error';
  result: ScanResponse | null;
  poll_after_ms?: number;
  error?: string;
  speech?: Speech;
};
