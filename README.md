# Collegentic

An autonomous college-application taskmaster: a multi-agent system (Google ADK +
Gemini) that researches college requirements from official sources, detects
conflicts across schools, matches existing essays to new prompts, prioritizes
work, and keeps a dashboard of what to do next — built for Google Cloud's "All
Things Agentic Hackathon" (Taskmaster track).

It is not a chatbot with a research button. The path is: **goal → plan →
research → analyze → compare → create tasks → prioritize → update state → ask
for human input when needed.**

## Try it now

**https://collegentic-git-74535340651.europe-west1.run.app**

Enter any college names you want (e.g. "MIT, Rice, Stanford") to watch the
real research pipeline run live — or click **Try Demo Mode** on the landing
screen for a pre-seeded profile (6 colleges, a real recommendation conflict,
overlapping essay prompts) with zero wait.

> The hosted instance may run a little slower than a local build — I capped
> `max-instances` at 3 to control cost after going over the hackathon's $150
> budget. Thanks for understanding!

## Run it yourself

Reproducible, from-source instructions — useful to confirm the app is real
and actually runs, not just a hosted demo. Written for someone who has never
used GCP or ADK before.

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (Python
  package/tool manager)
- Node.js 20+ and `npm`
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install)
- A GCP project with billing enabled

### 1. GCP project

```bash
# Create a project (or use an existing one) and set it as the active config
gcloud projects create YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID

# Enable the APIs this app actually uses
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# Create a Firestore database in Native mode (pick a region close to you)
gcloud firestore databases create --location=us-central1

# Application Default Credentials — used locally for both Gemini (Vertex AI)
# and Firestore, no separate API key needed
gcloud auth application-default login
```

### 2. Install `agents-cli`

```bash
uv tool install google-agents-cli
```

### 3. Configure the backend

```bash
cd agent
cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT to YOUR_PROJECT_ID
uv sync
```

### 4. Run it locally

Backend:
```bash
cd agent
uv run uvicorn app.fast_api_app:app --reload --port 8000
# or: agents-cli playground
```

Frontend (separate terminal):
```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`) — its dev
server proxies `/api/*` to the backend on port 8000, so both need to be
running.

## How it works

A student names the colleges they're applying to (natural language, or a
short list). `orchestrator_agent` parses that into a clean list and hands the
real work to a multi-stage pipeline as a single tool call, every requested
college researched concurrently:

1. **Identify** which named colleges are new vs. already tracked, resolving
   casual input (e.g. "MIT") to the full college name.
2. **Research** each new college from official sources (`google_search`,
   admissions/financial-aid pages preferred over secondary sources) —
   a fast branding/deadlines pass and a broader, slower requirements pass run
   concurrently for each college.
3. **Extract** structured, sourced requirements from the broader pass — with
   a confidence-checking refinement loop that does one targeted follow-up
   search when a finding is uncertain, rather than guessing.
4. **Plan tasks** from the full requirement set, categorized by type (essay,
   testing, recommendations, ...) so they can be filtered.
5. **Score priority** for every task and **score readiness** for every
   college — both via a deterministic algorithm in code, with Gemini adding
   a plain-language explanation on top.
6. **Detect conflicts** across colleges (recommendation policy differences,
   deadline clustering, ...) and **match** the student's existing essays
   against new prompts — concurrently, since neither depends on the other.
   Essay matching is plain deterministic Python (keyword-bucket
   categorization), not an LLM call.

Nothing here is invented: a requirement with no source, or a low-confidence
extraction, is surfaced as "needs verification," never guessed. Agents never
submit an application, submit an essay, or mark something "Complete" from
inference alone without a human approval step.

The Essay Editor (a grammar/spelling checker on the Essays page) is the one
place a Gemma model runs — Gemma takes a fast first pass, then Gemini 3.6
Flash always does its own independent check regardless of what Gemma finds.

Full architecture diagrams (system + full agent pipeline + essay matching +
the Essay Editor's grammar check) are in
[`docs/architecture-diagram.md`](docs/architecture-diagram.md). The full
technical spec — every scoring formula, every Firestore schema, and the
build-by-build record of what was found and fixed — is in
[`.agents-cli-spec.md`](.agents-cli-spec.md).

![System / deployment diagram](docs/assets/architecture-01-deployment.png)

## Project layout

```
agent/
  app/
    sub_agents/            # orchestrator_agent + the college-research pipeline (see docs/architecture-diagram.md)
    tools/                 # firestore_tools.py, scoring.py (deterministic formulas)
    api.py                 # REST routes, mounted at /api
    fast_api_app.py        # ADK app + REST routes + bundled frontend, one Cloud Run service
  tests/
    unit/  integration/    # pytest — code correctness, not agent behavior
    eval/                  # agents-cli eval — agent behavior, LLM-judged
  scripts/build_frontend.sh  # builds frontend/, stages it for the Docker build
  Dockerfile
frontend/
  src/
    pages/  components/  lib/api.ts
docs/
  architecture-diagram.md
  assets/                  # blueprint-style architecture diagram images
.agents-cli-spec.md         # full technical spec + build-by-build findings log
```

## Tests

```bash
cd agent
uv run pytest tests/unit tests/integration
```

Pytest covers code correctness (schema validation, deterministic scoring
formulas, API contracts) — never LLM output content, which is
non-deterministic by nature.

## Evaluation

Agent *behavior* (not code correctness) is graded with `agents-cli eval`
against an LLM-judge rubric covering grounding, human-in-the-loop safety,
explainable scoring, cross-college reasoning, and clarification-over-guessing.
See [`agent/tests/eval/datasets/README.md`](agent/tests/eval/datasets/README.md)
for the exact reproduction commands and why this suite captures traces via
`InMemoryRunner` rather than the standard `eval generate` path.

## Deployment

The frontend is bundled into the same Cloud Run service as the backend — one
image, one URL, no separate frontend host.

The hosted instance above deploys itself: [`cloudbuild.yaml`](cloudbuild.yaml)
is wired to a Cloud Build trigger that rebuilds and redeploys the
`collegentic-git` service on every push to `main`, staging `frontend/` into
`agent/frontend_dist` before building `agent/Dockerfile` (the build context
Cloud Build's own console-generated trigger assumes is a root-level
Dockerfile, which this repo — `frontend/` and `agent/` as siblings — doesn't
have).

To deploy your own copy manually instead, `agents-cli deploy` builds from
`agent/`, which doesn't see `frontend/` as a sibling directory, so build the
frontend first:

```bash
cd agent
./scripts/build_frontend.sh
agents-cli deploy --memory 1Gi --cpu 1 --min-instances 0 --max-instances 3
```

`agents-cli deploy` always deploys as auth-required; there's no flag to make
it public. If you want the URL publicly viewable (e.g. for a demo link),
grant it after deploying:

```bash
gcloud run services add-iam-policy-binding agent \
  --region us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

## Troubleshooting

Gotchas actually hit while building and deploying this, in case they save
someone else the same detour:

- **`403` from `agents-cli deploy`'s own pre-flight check.** The Cloud Run
  Admin API (and friends — Cloud Build, Secret Manager, Artifact Registry)
  aren't enabled by default on a fresh project. See the `gcloud services
  enable` step above.
- **`gcloud run deploy --update-env-vars` rejects a comma-containing value**
  with "Bad syntax for dict arg." `--update-env-vars` splits on comma for
  both the `KEY=VALUE` pair separator *and* inside a single value — a
  multi-origin `ALLOW_ORIGINS=http://a,http://b` breaks it. Pass an override
  with a single value at deploy time
  (`--update-env-vars "ALLOW_ORIGINS=..."`) instead of trying to smuggle a
  list through; production doesn't need multi-origin CORS anyway since the
  bundled frontend calls `/api/*` same-origin.
- **Every non-`GET` request from the frontend dev server returns 403.** ADK's
  built-in origin-check middleware (DNS-rebinding protection) compares the
  browser's `Origin` header against the backend's own host:port — Vite's dev
  server runs on a different port, so it fails the check unless explicitly
  allow-listed. Set `ALLOW_ORIGINS` in `agent/.env` (see `.env.example`).
  `curl`-based testing won't catch this: curl never sends an `Origin` header.
- **A deadline renders one calendar day early** for anyone west of UTC.
  Deadlines are stored as UTC-midnight calendar dates, not moments in time —
  formatting with the viewer's local timezone shifts the date. Format with
  `timeZone: "UTC"` for anything that's a date, not a timestamp.

## Constraints this system holds itself to

- Never invent a requirement, deadline, or source — missing/unclear data is
  `needs_verification` / `confidence: low`, never a guess.
- Official sources are preferred over secondary ones; secondary-source use is
  flagged in the UI.
- No agent can submit an application or essay, fabricate an accomplishment,
  claim a requirement is satisfied without evidence, or send external
  communication — none of those tools exist in this system.
- No agent ever marks a requirement/task "Complete" or "Submitted" on its
  own — task status changes only come from an explicit student action, never
  from agent inference. (A `PendingAction` schema + Firestore tools exist for
  a future approval-gated write path; no agent calls them yet in this build.)
- Every agent defaults to `gemini-3.6-flash`; research is cached in Firestore
  and only re-run for new colleges, an explicit refresh, or a failed
  confidence check.
