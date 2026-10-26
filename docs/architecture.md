# AI Application Auditor: architecture and task split

Status: **draft for @anu's review.** Nothing here is final until @anu approves it.

## 1. What we're building

The Auditor is an agent that acts like an on-call SRE. When an incident happens, it reads the team's code, logs, deploy history and metrics. It then finds the root cause, backs every claim with evidence, writes a fix plan, and opens the fix as a pull request.

The demo uses a **synthetic** job board that we build during the event. It reproduces the kind of incident we saw: job posts with expired deadlines break a database rule, and the site only returns a generic 500. The demo contains no real KennaJobs code, logs or data.

## 2. Constraints from the rules

| Constraint | What it means for the design |
|---|---|
| The repo must be public when we submit | Zero secrets, keys, real data or personal data, ever, including git history. Config comes from env vars, and the repo only contains `.env.example`. Secret scanning runs in CI and in a pre-commit hook. |
| The demo video is at most 3 minutes and shows only event-built work | One incident, shown end to end, at a pace that fits 3 minutes. The UI shows the investigation live so the video tells the story. |
| Meta Model API is blocked in Ethiopia | We use Muse Spark Open (open weights) through Baseten, Modal, Fireworks or OpenRouter. The model client is provider-agnostic: an OpenAI-compatible endpoint chosen by env var. |
| Judging: Impact 30%, Meta tooling 25%, Technical depth 20%, Demo 25% | The core loop runs entirely on the Meta model. Every claim the agent makes is grounded in evidence. The agent verifies its fix by running tests before it opens a PR. An eval set shows the agent works on more than one incident. |
| @anu must own an original submission | All code is written during the event. Any open-source dependency's license is listed in `docs/licenses.md`. |

## 3. System overview

```
 incident trigger (alert / manual)
            │
            ▼
 ┌─────────────────────────┐      ┌───────────────────────────┐
 │  Auditor agent (Python) │◀────▶│ Model adapter             │
 │  plan → gather → reason │      │ OpenAI-compatible client  │
 │  → verify → report      │      │ Muse Spark Open via env   │
 └──────────┬──────────────┘      └───────────────────────────┘
            │ tool calls (read-only, except patch/PR)
            ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Tools                                                    │
 │ logs.search · logs.trace · code.grep · code.read         │
 │ git.log · git.blame · deploys.list · metrics.query       │
 │ db.schema (read-only) · patch.apply_in_sandbox           │
 │ tests.run · github.open_pr                               │
 └──────────┬───────────────────────────────────────────────┘
            ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Demo target: synthetic job board                         │
 │ FastAPI + Postgres, JSON logs, deploy history, metrics   │
 │ incident scenarios injected by scripts in incidents/     │
 └──────────────────────────────────────────────────────────┘
            │
            ▼
 Web UI: live investigation timeline + final incident report + PR link
```

### 3.1 Components

1. **Model adapter** (`auditor/model/`)
   - Talks to an OpenAI-compatible `/chat/completions` endpoint with tool calling.
   - Config comes from env vars: `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`.
   - Keeps an ordered list of fallback providers, retries on errors, and logs token usage.
   - Day 1 risk: we haven't confirmed which providers host Muse Spark Open, or whether they support tool calling. If tool calling isn't supported, the adapter falls back to tool calls in JSON mode, validated against a schema.

2. **Auditor agent** (`auditor/core/`)
   - A bounded loop with five stages: **plan** (form hypotheses) → **gather** (tool calls) → **reason** (narrow down the hypotheses) → **verify** (reproduce the bug, patch it, run the tests) → **report**.
   - Every finding cites its evidence, such as a log line ID or a `file:line`. The report generator rejects any claim that has no citation.
   - It has a step budget and a token budget, and writes a full trace to JSON for replay in the UI.

3. **Tools** (`auditor/tools/`)
   - Typed functions with JSON schemas. All tools are read-only except two:
     - `patch.apply_in_sandbox` applies a patch to a throwaway git worktree.
     - `github.open_pr` opens a PR on the demo app's repo, using a token from env vars only.
   - Each tool's output is truncated and summarized so the model's context stays small.

4. **Demo target** (`apps/jobboard/`)
   - A small FastAPI and Postgres job board. Its schema has a `CHECK` constraint on job deadlines.
   - Its error handler is the bug: it hides the real error and returns a generic 500.
   - It writes structured JSON logs, keeps a deploy history file, and exposes basic metrics.

5. **Incident scenarios** (`incidents/`)
   - Scripts that inject a bug, generate traffic, and produce the logs and telemetry.
   - Incident 1 (the demo) is the expired-deadline `CHECK` violation behind a generic 500.
   - Incidents 2 and 3 are for evals, for example a missing env var after a deploy and an N+1 slowdown.

6. **Web UI** (`web/`)
   - A FastAPI backend that streams agent steps over SSE, and a minimal frontend.
   - The page shows a timeline of steps, the evidence behind each claim, a diff of the fix, and a link to the PR.

7. **Evals** (`evals/`)
   - Runs the agent on each incident and scores whether it found the root cause, whether its fix passes the tests, and how many steps and tokens it used.
   - The results table goes in the README, as evidence for the technical depth score.

### 3.2 Stack

- Python 3.12, FastAPI, Postgres 16 in Docker Compose.
- Dependencies managed with `uv`. `pytest` for tests, `ruff` for lint.
- `gitleaks` in CI and as a pre-commit hook.
- GitHub Actions runs lint, tests and a secret scan on every PR.

### 3.3 Repository layout

```
apps/jobboard/      demo target (synthetic)
auditor/model/      provider-agnostic model client
auditor/core/       agent loop, budgets, trace, report
auditor/tools/      tool implementations + schemas
incidents/          scenario injectors + generated fixtures
evals/              eval runner + results
web/                UI (SSE timeline)
docs/               architecture, licenses, demo script
.env.example        every env var, no values
```

## 4. Workflow

- Every change goes through a branch and a PR. Nothing is pushed straight to `main`.
- Review order: @hark reviews first, then @claude makes the technical call, then @anu has the final say and merges.
- A PR can only merge when CI passes: lint, tests and the secret scan.
- Each PR covers one task from the split below and states its acceptance criteria.

## 5. Milestones (EAT)

| Date | Milestone | Done when |
|---|---|---|
| Oct 26–27 | **M0 Foundation** | The repo has its skeleton and CI is green. `.env.example` and gitleaks are in place. The model spike has returned a tool call from Muse Spark Open on at least one provider. |
| Oct 28–29 | **M1 Demo target** | The job board runs in Docker. Incident 1 reproduces, and its logs, deploys and metrics are generated. |
| Oct 29–31 | **M2 Agent core** | The agent finds incident 1's root cause with cited evidence. The trace is saved. |
| Nov 1 | **M3 Fix and PR** | The agent writes a patch, the tests pass in the sandbox, and it opens a PR on the demo repo. |
| Nov 2 | **M4 UI and evals** | The live timeline UI works. Incidents 2 and 3 run, and the eval table is generated. |
| Nov 3 | **M5 Polish** | The README, licenses, demo script and a draft video are done. |
| Nov 4, by 20:00 | **Submit** | The repo is public and checked in a logged-out browser. The 3-minute video is uploaded. The project is submitted on Cerebral Valley. |

## 6. Task split (proposed; @anu to confirm assignments)

| ID | Task | Owner (proposed) | Depends on |
|---|---|---|---|
| T0 | Create the repo skeleton, CI, pre-commit, gitleaks and `.env.example` (this PR) | Claude Code | none |
| T1 | Model spike: confirm which providers host Muse Spark Open, test tool calling, measure latency, and record the results | @claude + @anu (accounts and keys) | none |
| T2 | Model adapter with provider fallback | Claude Code | T1 |
| T3 | Demo job board app, schema and the bugged error handler | OpenCode | T0 |
| T4 | Incident 1 injector, traffic generator and telemetry fixtures | @muse | T3 |
| T5 | Read-only tools: logs, code, git, deploys, metrics, db.schema | Claude Code | T0 |
| T6 | Agent loop, budgets, trace and the citation-enforced report | @claude (design) / Claude Code (build) | T2, T5 |
| T7 | Sandboxed patch tool, test runner and the GitHub PR tool | OpenCode | T6 |
| T8 | Web UI with the SSE timeline | @cue | T6 trace format |
| T9 | Incidents 2 and 3, plus the eval runner | @muse | T4, T6 |
| T10 | README, licenses, demo script and video | @anu + @hark | T8 |
| R | First review on every PR | @hark | none |

Owners are a proposal. I don't yet know each agent's strengths, or whether Hermes, which joined the channel today, is part of the team.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Muse Spark Open is unavailable, or doesn't support tool calling on any provider | T1 runs first. The adapter falls back to JSON-mode tool calls. Fallback providers are listed in config. |
| A secret leaks into the public repo's history | gitleaks runs in pre-commit and CI. All config comes from env vars only. Before going public, we audit the whole history. |
| The demo doesn't work live | A recorded trace can be replayed in the UI, and the video uses a deterministic seed. |
| Time runs out | M2 is the minimum viable demo. M4's eval work gets cut first. |

## 8. Open questions for @anu

1. Did kickoff open Meta Model API access or credits in Ethiopia, or do we stay on partner providers only?
2. Which agents are actually available, and should the owners in §6 change?
3. Is MIT the right license? It's in this PR as the default and can be swapped before merge.
