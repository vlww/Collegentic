# Collegentic

Collegentic is an autonomous college-application platform that utilizes Agentic AI to reduce the workload for students. It incorporates a multi-agent system (Google ADK +
Gemini) to research college requirements from official sources, detect
conflicts across schools, match existing essay ideas to new prompts, prioritize
tasks, and maintain a concise dashboard. Built for Google Cloud's All
Things Agentic Hackathon in the Taskmaster track.

## Hosted Link

**https://collegentic-git-74535340651.europe-west1.run.app**

Enter any college names you want to watch the
real research pipeline run live! You can also click **Try Demo Mode** on the landing
screen for a pre-seeded profile including 6 colleges, a real recommendation conflict,
and overlapping essay prompts with zero wait.

> The hosted instance may take a few minutes to load when you first run it as the Cloud Run service may scale down when it isn't being used.
> Additionally, the platform may run a little slower than a local build, as I capped
> `max-instances` at 3 to control costs and reduce the risk of going over budget.
> Thanks for your understanding!

## Run it Locally

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (Python
  package/tool manager)
- Node.js 20+ and `npm`
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install)
- A GCP project with billing enabled

### 1. GCP project

```bash
gcloud projects create YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID

gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

gcloud firestore databases create --location=us-central1

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

uv sync
```

### 4. Run it locally

Backend:
```bash
cd agent
uv run uvicorn app.fast_api_app:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`). Its dev
server proxies `/api/*` to the backend on port 8000, so both need to be
running.

## How Collegentic Works

A student names the colleges they're applying to (natural language, or a
short list). `orchestrator_agent` parses that into a clean list and hands the
real work to a multi-stage pipeline as a single tool call, every requested
college researched concurrently:

1. Identify which named colleges are new vs. already tracked, resolving
   casual input ("MIT", "UIUC", "Cal", etc.) to the full college name.
2. Research each new college from official sources (`google_search`,
   admissions/financial-aid pages preferred over secondary sources). A fast
   branding/deadlines pass and a broader, slower requirements pass run
   concurrently for each college.
3. Extract structured, sourced requirements from the broader pass, with a
   confidence-checking refinement loop that does one targeted follow-up
   search when a finding is uncertain, rather than guessing.
4. Plan tasks from the full requirement set, categorized by type (essay,
   testing, recommendations, etc.) so they can be filtered.
5. Score priority for every task and score readiness for every college,
   both via a deterministic algorithm in code, with Gemini adding a
   plain-language explanation on top.
6. Detect conflicts across colleges (recommendation policy differences,
   deadline clustering, etc.) and match the student's existing essays against
   new prompts, concurrently, since neither depends on the other. Essay
   matching is plain deterministic Python (keyword-bucket categorization),
   not an LLM call.

The Essay Editor (a grammar/spelling checker on the Essays page) is the one
place a Gemma model runs. Gemma takes a fast first pass, then Gemini 3.6
Flash always does its own independent check regardless of what Gemma finds.

Full architecture diagrams (system + full agent pipeline + essay matching +
the Essay Editor's grammar check) are in
[`docs/architecture-diagram.md`](docs/architecture-diagram.md). A shorter overview can be found in [`docs/concise-architecture-diagram.pdf`](docs/concise-architecture-diagram.pdf) The full
technical spec, every scoring formula, every Firestore schema, and the
build-by-build record of what was found and fixed, is in
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
    unit/  integration/    # pytest: code correctness, not agent behavior
    eval/                  # agents-cli eval: agent behavior, LLM-judged
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

## Deployment

The frontend is bundled into the same Cloud Run service as the backend: one
image, one URL, no separate frontend host.

The hosted instance above deploys itself. [`cloudbuild.yaml`](cloudbuild.yaml)
is wired to a Cloud Build trigger that rebuilds and redeploys the
`collegentic-git` service on every push to `main`, staging `frontend/` into
`agent/frontend_dist` before building `agent/Dockerfile`. (Cloud Build's own
console-generated trigger assumes a root-level Dockerfile; this repo has
`frontend/` and `agent/` as siblings instead, so the build script stages
things first.)

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
