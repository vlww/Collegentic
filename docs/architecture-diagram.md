# Architecture

Two views: how the deployed system fits together, and what the agent pipeline
actually does when a student adds colleges.

## System / deployment

One Cloud Run service serves everything — the built React frontend as static
files, the REST API, and the ADK agent runtime (including its A2A surface).
There is no separate frontend host and no second backend.

```mermaid
flowchart TB
    Browser["Browser<br/>(React SPA)"]
    A2AClient["External A2A client<br/>(e.g. Gemini Enterprise)"]

    subgraph CloudRun["Cloud Run service — one image, one URL"]
        Static["Static files<br/>frontend_dist/ (Vite build)"]
        REST["REST API<br/>/api/* (app/api.py)"]
        AgentRuntime["ADK agent runtime<br/>orchestrator_agent + pipeline"]
        A2ASurface["A2A surface<br/>/a2a/app (JSON-RPC + agent card)"]
    end

    Firestore[("Firestore<br/>users/{userId}/...")]
    Vertex["Vertex AI<br/>Gemini (gemini-3.6-flash) + Search grounding"]

    Browser -- "GET / and client routes" --> Static
    Browser -- "GET/POST /api/*" --> REST
    Browser -- "POST /api/orchestrator/messages" --> AgentRuntime
    A2AClient -- "JSON-RPC" --> A2ASurface
    A2ASurface --> AgentRuntime

    REST --> Firestore
    AgentRuntime --> Firestore
    AgentRuntime --> Vertex
```

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
- **Cost shape.** `min-instances=0` (scales to zero between demos),
  `max-instances=3`, `1Gi`/`1 vCPU` — sized for a low-traffic hackathon demo,
  not sustained load.

## Agent pipeline

`orchestrator_agent` is the only agent the frontend talks to directly (via
`POST /api/orchestrator/messages`). It parses which colleges a student
means, then hands off the actual work as a single `AgentTool` call to
`college_intake_pipeline` — a `SequentialAgent` of seven stages — and turns
the result into a plain-language summary. It does no research or extraction
itself.

```mermaid
flowchart TB
    Orchestrator["orchestrator_agent (root LlmAgent)<br/>parses college names, summarizes results"]

    Intake1["1. college_intake_agent<br/>which names are new vs. already tracked"]
    Intake2["2. college_research_agent<br/>google_search — official sources only"]
    ReqAgent["3a. requirements_agent<br/>extracts structured, sourced Requirements"]
    Evaluator["3b. findings_evaluator<br/>flags low-confidence requirements"]
    Followup["3c. findings_followup_search<br/>targeted re-search — loops back to 3b, max 2 iters"]
    ConflictP["4a. conflict_pipeline<br/>conflict_agent"]
    EssayP["4b. essay_matching_pipeline<br/>essay_matching_agent"]
    Intake5["5. task_planning_pipeline<br/>task_planning_agent"]
    Intake6["6. priority_pipeline<br/>priority_agent — compute_priority_score + LLM explanation"]
    Intake7["7. readiness_pipeline<br/>readiness_agent — compute_readiness_score + LLM explanation"]

    Orchestrator -- "AgentTool(college_intake_pipeline)" --> Intake1
    Intake1 --> Intake2 --> ReqAgent --> Evaluator
    Evaluator --> Followup
    Followup -. "re-evaluate" .-> Evaluator
    Evaluator --> ConflictP
    Evaluator --> EssayP
    ConflictP --> Intake5
    EssayP --> Intake5
    Intake5 --> Intake6 --> Intake7
    Intake7 -. "state_delta forwarded back<br/>(findings, conflicts, tasks, readiness)" .-> Orchestrator
```

Stage 3 (`requirements_pipeline`) is itself a `SequentialAgent` wrapping a
`LoopAgent` (`requirements_confidence_loop`, capped at 2 iterations); stage 4
(`cross_college_analysis`) is a `ParallelAgent` — `conflict_pipeline` and
`essay_matching_pipeline` run concurrently, both reading only what stage 3
already wrote, then stage 5 waits for both.

Two things worth calling out that aren't obvious from the shape alone:

- **`conflict_pipeline` and `essay_matching_pipeline` run concurrently**
  (Milestone 11) because neither depends on the other's output — both only
  read `Requirement`/`Recommendation`/`StudentMaterial` docs already written
  by the requirements stage.
- **Scoring is deterministic code, not an LLM guess.** `priority_agent` and
  `readiness_agent` each call a plain-Python formula
  (`compute_priority_score` / `compute_readiness_score` in
  `app/tools/scoring.py`) and only use the LLM to turn the already-computed
  number into a plain-language explanation — the same "business rule in
  code, LLM for judgment" split used throughout.
- **`AgentTool`, not a `sub_agents` transfer**, is what lets control return
  to `orchestrator_agent` after the pipeline finishes instead of ending the
  turn on the pipeline's raw JSON output — and it's why `raw_research_findings`,
  `detected_conflicts`, `planned_tasks`, etc. all land back in the
  Orchestrator's own session state for it to summarize.
