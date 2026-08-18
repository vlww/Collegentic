# Collegentic

An autonomous college-application taskmaster: a multi-agent system (Google ADK + Gemini)
that researches college requirements from official sources, detects conflicts across
schools, matches existing essays to new prompts, prioritizes work, and keeps a dashboard
of what to do next — built for Google Cloud's "All Things Agentic Hackathon" (Taskmaster
track).

> This README is intentionally minimal during early development. The full version (setup,
> architecture diagram, deployment, troubleshooting, demo script) lands in Milestone 18.
> For the full technical spec in the meantime, see [`.agents-cli-spec.md`](.agents-cli-spec.md).

## Status

Milestone 1 (project scaffolding) complete: ADK backend + React frontend scaffolded,
wired to a real GCP project (`collegentic-hackathon`, Vertex AI), health-checked
end-to-end. Product features are not built yet — see `.agents-cli-spec.md` for the
milestone plan.

## Project layout

```
agent/       ADK Python backend (FastAPI + multi-agent pipeline) — Cloud Run target
frontend/    React + TypeScript (Vite) dashboard UI
```

## Local development

Backend:
```bash
cd agent
uv sync
uv run uvicorn app.fast_api_app:app --reload --port 8000
# or: agents-cli run "..."   /   agents-cli playground
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

The frontend dev server proxies `/api/*` to `http://127.0.0.1:8000`.

Requires a `.env` in `agent/` (see `agent/.env.example`) pointing at a GCP project with
the Vertex AI API enabled, and `gcloud auth login --update-adc` run locally.

## Tests

```bash
cd agent
uv run pytest tests/unit tests/integration
```
