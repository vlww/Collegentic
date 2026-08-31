# Architecture

Four views: how the deployed system fits together, what the college-research
agent pipeline actually does, how essay reuse matching works (no LLM at
all), and how the Essay Editor's grammar check works (the one place Gemma
runs).

## System / deployment

One Cloud Run service serves everything — the built React frontend as static
files, the REST API, and the ADK agent runtime (including its A2A surface).
There is no separate frontend host and no second backend.

Two different AI backends are in play, not one: **Vertex AI** serves every
Gemini call in the app (the Orchestrator, the whole research pipeline, and
half of the grammar check). **Google AI Studio** serves Gemma, and only
Gemma — this project's Vertex AI Model Garden access doesn't include Gemma
at all (confirmed live: `client.models.list()` against Vertex lists 24
Gemini models and zero Gemma ones), so the grammar check's Gemma call is
routed through AI Studio via its own API key instead.

![System / deployment diagram](assets/architecture-01-deployment.png)

Notes on choices this reflects (see `.agents-cli-spec.md` for the full
reasoning trail):

- **Why one service, not frontend/backend split.** The ADK scaffold already
  generates a FastAPI app to host the agent runtime; extending it to also
  serve `/api/*` and the built frontend avoids standing up a second service
  just to host CRUD routes and static files (Milestone 17).
- **Why Firestore, not a relational DB.** Every collection lives under
  `users/{userId}/...` — no cross-user joins are ever needed, and the
  document shapes (Requirement, Task, Conflict, ...) map directly onto the
  Pydantic schemas agents already validate against before writing.
- **Why no OAuth yet.** `userId` is a client-generated UUID in
  `localStorage`, sent as a header — an explicit MVP seam that real Google
  auth replaces later, not a security model for production use.
- **Why two AI backends.** Gemini (Vertex AI, ambient ADC — no key to
  manage) handles everything else in the app. Gemma is only ever called for
  the Essay Editor's first grammar-check pass, and only through AI Studio's
  `GEMINI_API_KEY` — every other agent's Vertex/ADC configuration is
  untouched by that.
- **PDF upload never touches the backend.** Extracting a title/topic/body
  from an uploaded PDF (`pdf.js`, real paragraph reconstruction from each
  line's position on the page) happens entirely client-side in the browser,
  before the material is ever submitted to `POST /api/materials`.
- **Cost shape.** `min-instances=0` (scales to zero between demos),
  `max-instances=3`, `1Gi`/`1 vCPU` — sized for a low-traffic hackathon demo,
  not sustained load.

## Agent pipeline (college research)

`orchestrator_agent` is the only agent the frontend talks to directly (via
`POST /api/orchestrator/messages`). It parses which colleges a student
means, then hands off the actual work as a single `AgentTool` call to
`college_intake_pipeline`, and turns the result into a plain-language
summary. It does no research or extraction itself.

![Multi-agent research pipeline diagram](assets/architecture-02-pipeline.png)

Every college requested in the same message runs stage 2 concurrently (not
one college fully at a time), and within one college, its `Detailed` and
`Quick` branches also run concurrently — six workstreams for two colleges,
not two.

Worth calling out, since none of this is obvious from the shape alone:

- **Every requested college is researched concurrently, in a fully isolated
  session per college.** Found live, in steps: batching every college into
  one shared LLM call meant every college's data became known at the same
  instant (no real per-college progress); looping colleges one at a time
  fixed that but made total wait time scale linearly with college count;
  running them concurrently, each in its own throwaway session, fixed both —
  nothing for two colleges' writes or citation sources to collide on.
- **Each college's `Detailed` and `Quick` branches are two independently
  timed-out and retried workstreams, not one joined unit.** `Quick`
  (branding, then deadlines) is deliberately the smallest, fastest possible
  research — color/logo can land and the row can visibly tint before
  deadline queries have even started — while `Detailed` runs the full,
  slower research sweep. Splitting them means a stuck `Quick` call never
  forces a retry of the much more expensive `Detailed` pass for the same
  college, and vice versa.
- **`cross_college_analysis` now runs LAST, after Tasks/Priority/Readiness —
  not right after research, like an earlier version of this pipeline had
  it.** Neither conflict detection nor essay matching feeds task planning,
  priority, or readiness, so there's no correctness reason for Tasks and
  Readiness — what a student actually watches for right after research
  finishes — to sit behind two more full passes that don't feed either of
  them.
- **Essay matching is deterministic Python now, not an LLM call at all** —
  see the next section. `conflict_pipeline` and `essay_matching_pipeline`
  still run concurrently inside `cross_college_analysis` (neither depends on
  the other's output), it's just that only one of the two is actually an
  `LlmAgent` these days.
- **Scoring is deterministic code, not an LLM guess.** `priority_agent` and
  `readiness_agent` each call a plain-Python formula
  (`compute_priority_score` / `compute_readiness_score` in
  `app/tools/scoring.py`) and only use Gemini to turn the already-computed
  number into a plain-language explanation, batched into one call per stage
  regardless of task/college count — the same "business rule in code, LLM
  for judgment" split used throughout this pipeline.
- **`AgentTool`, not a `sub_agents` transfer**, is what lets control return
  to `orchestrator_agent` after the pipeline finishes instead of ending the
  turn on the pipeline's raw JSON output — and it's why `raw_research_findings`,
  `detected_conflicts`, `planned_tasks`, etc. all land back in the
  Orchestrator's own session state for it to summarize.

## Essay reuse matching (deterministic — no LLM)

`essay_matching_agent` used to be a two-stage `LlmAgent` pipeline. It's now
a plain Python keyword-bucket categorizer (`app/tools/essay_matching.py`):
a prompt and a material either land in the same broad category (personal
statement, why-this-major, greatest challenge, ...) or they don't — that
binary bucket match is the actual signal the Essay Map graph needs to draw
a connection, and it's free and instant to compute versus judging thematic
overlap with an LLM call.

Being free is also why it isn't only triggered by a college-research run —
it fires directly and synchronously from material CRUD too, so adding an
essay connects it to matching prompts immediately instead of only after the
student's next research run:

![Essay reuse matching diagram](assets/architecture-03-essay-matching.png)

## Essay Editor grammar check (Gemma + Gemini)

The only place Gemma runs. Triggered directly from the Essays page's Essay
Editor via `POST /api/grammar-check` — a plain REST route
(`app/tools/grammar_check.py`), not an ADK agent and not part of
`college_intake_pipeline`.

Two models, not one, and Gemini always runs regardless of what Gemma
returns:

![Essay Editor grammar check diagram](assets/architecture-04-grammar-check.png)

- **Gemma 4, 26B-A4B-it** (a mixture-of-experts model, 26B total params, ~4B
  active) does a fast first pass. It's genuinely a smaller, less reliable
  model than Gemini at this task.
- **Gemini 3.6 Flash always runs its own independent detection pass**, not
  just a validator narrowing down Gemma's list. Found live: an earlier
  version only asked Gemini to narrow Gemma's candidates, and returned zero
  issues the instant Gemma's own output was empty or unparseable — a real,
  frequent outcome for a model this small — so Gemini never even looked at
  the essay in that case. Now Gemma's candidates are folded in only as a
  hint of where to look first; Gemini is told explicitly not to let an empty
  hint list stop it from checking every sentence itself.
- **Every returned issue is re-verified in Python** against the literal
  essay text before it's ever shown — an issue whose `original` text isn't
  a real substring of the essay is dropped rather than shown broken (it
  couldn't be highlighted correctly client-side anyway).
- Gemma gets its own short ~10s timeout, separate from Gemini's normal 45s
  budget — since Gemma's result is a hint, not a requirement, a slow/hung
  Gemma call shouldn't cost the student most of a minute before Gemini's
  real detection pass even starts.
