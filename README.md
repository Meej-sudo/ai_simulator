# AI Incident Trainer POC

A modular-monolith proof of concept for organizational cyber-incident exercises. The simulation is deterministic; an LLM is used only to render a role's permitted knowledge as natural language.

## What is implemented

- YAML scenario compiler with strict Pydantic validation and cross-reference checks
- Deterministic variant materialization with ground truth kept out of public API and LLM requests
- Logical simulation clock and interval-based timeline processing
- PostgreSQL/SQLAlchemy session state plus an append-only audit event log
- Event-replayed per-role knowledge and explicit `share_fact` transfers
- Provider-neutral `LLMProvider` with deterministic fake, OpenAI, and Ollama providers
- Pydantic structured LLM output, knowledge-boundary validation, one retry, violation events, and a safe fallback
- Rule-based evaluation and structured debrief data
- FastAPI endpoints and generated OpenAPI documentation
- Minimal Next.js incident-room UI
- Docker Compose for PostgreSQL, backend, and frontend

## Architectural boundary

The data flow for a role response is intentionally one way:

```text
variant-resolved evidence + session event log
                    |
                    v
          role knowledge engine
                    |
                    v
       constrained LLM request only
                    |
                    v
      validate referenced fact IDs
                    |
                    v
             audited response
```

Variant `ground_truth` is never included in `RoleResponseRequest`. Timeline events that have not fired and other roles' unshared knowledge are also excluded. The OpenAI adapter uses Pydantic structured output through `responses.parse` and sets `store=False`. All numerical scoring remains deterministic application code.

## Run with Docker

The default configuration uses `FakeLLMProvider`, so no API key is required:

```bash
docker compose up --build
```

Then open:

- UI: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

The browser uses the frontend's same-origin `/api` path. Next.js proxies those
requests to the backend service, so the UI also works when opened through a server
IP or hostname without requiring browser CORS configuration.

To use OpenAI, copy `.env.example` to `.env`, set `LLM_PROVIDER=openai`, and provide `OPENAI_API_KEY`. `OPENAI_MODEL` is configurable.

To use the local Ollama server, set these values in `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://your-ollama-host:11434
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_TIMEOUT_SECONDS=300
```

The Ollama adapter calls the native `/api/chat` endpoint with a JSON schema for
`RoleResponse`. Responses still go through the same knowledge-boundary validation,
retry, safe fallback, and audit logging as the other providers. Rebuild and recreate
the backend after enabling the provider:

```bash
docker compose up -d --build backend
```

## Backend development

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
cd backend
DATABASE_URL=sqlite+pysqlite:///./trainer.sqlite3 pytest -q
DATABASE_URL=sqlite+pysqlite:///./trainer.sqlite3 uvicorn app.main:app --reload
```

The application defaults the scenario directory to the repository's `scenarios/` folder. Set `SCENARIOS_PATH` to load a different catalog.

For PostgreSQL schema migrations:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://trainer:trainer@localhost:5432/trainer alembic upgrade head
```

## API surface

```text
GET  /health
GET  /scenarios
GET  /scenarios/{id}

POST /sessions
GET  /sessions/{id}
POST /sessions/{id}/start
POST /sessions/{id}/advance-time
POST /sessions/{id}/complete

GET  /sessions/{id}/roles
GET  /sessions/{id}/roles/{role_id}/knowledge
POST /sessions/{id}/ask
POST /sessions/{id}/actions/share-fact
POST /sessions/{id}/actions/decision
GET  /sessions/{id}/events
GET  /sessions/{id}/evaluation
```

Decision categories are authored per scenario and returned by `GET /scenarios`.
The trainee selects only a broad category and writes the actual decision:

```json
{
  "actor_role": "ciso",
  "category": "containment",
  "decision": "Isolate the affected servers while preserving emergency access.",
  "confidence": null,
  "rationale": "Encryption is continuing and lateral movement remains possible."
}
```

The event log preserves the free-text decision, while deterministic evaluation
matches only category, timing, and optional structured confidence. Detailed
evaluation is available only after the session has been completed.

Example session start:

```bash
curl -s http://localhost:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"scenario_id":"ransomware_001","variant_id":"track_alpha"}'
```

Use the returned session ID to start and advance the logical clock:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/start
curl -X POST http://localhost:8000/sessions/SESSION_ID/advance-time \
  -H 'content-type: application/json' \
  -d '{"minutes":45}'
```

## Authoring scenarios

Each scenario directory contains:

```text
scenario.yaml   metadata and duration
roles.yaml      role identity, responsibilities, and style
facts.yaml      stable observable/assessment fact definitions
timeline.yaml   deterministic knowledge grants at relative minutes
variants.yaml   isolated ground truth and deterministic overrides
scoring.yaml    deterministic scoring rules
```

The compiler rejects duplicate IDs, unknown roles/facts/events, events beyond the scenario duration, malformed type-specific scoring rules, and invalid merged variant overrides. The included `ransomware_001` scenario has four roles and two neutral public tracks whose hidden exfiltration outcomes differ.

## Tests

```bash
cd backend
../.venv/bin/pytest -q
```

The suite covers compiler failures, deterministic variant resolution, logical time boundaries, knowledge isolation and transfer, evaluation, and the LLM boundary retry/fallback behavior.
