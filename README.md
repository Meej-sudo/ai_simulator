# AI Incident Trainer POC

A deterministic, AI-assisted cyber-incident exercise for practicing information
discovery, role coordination, decisions, and assessment under uncertainty.

The application owns scenario truth, time, evidence visibility, investigation
outcomes, and scoring. An LLM is used only for three constrained language tasks:

1. Render a role response from evidence already known to that role.
2. Route a free-text investigation request to a currently eligible public
   investigation definition.
3. Normalize a trainee's free-text assessment into public hypotheses,
   confidence, and a basis containing only evidence known to the acting role.

The LLM never decides an investigation outcome, advances time, reveals evidence,
grades an assessment, or receives variant ground truth.

## Sprint 1 capabilities

- First-class observations, findings, hypotheses, and investigations
- Ambiguous timeline observations that do not reveal the scenario answer
- Free-text investigation requests with provider-neutral LLM interpretation
- Deterministic, variant-specific investigation outcomes
- Investigation prerequisites, durations, non-repeatability, and exact-time
  completion
- Findings isolated to the performing role until explicitly shared
- Free-text assessments with append-only history and a latest-per-hypothesis
  projection
- No correctness signal while an exercise is running
- Role chat constrained to that role's current observations and findings
- Public event payload redaction for role-scoped evidence
- Minimal process scoring migrated to evidence and assessment events
- A form-based scenario editor for all Sprint 1 concepts
- Strict Pydantic validation and cross-reference checks across nine YAML files
- Deterministic fake, OpenAI, and Ollama LLM adapters
- External entities retained as an existing extension for authorities, police,
  media, and other communication recipients

## Core concepts

- **Observation**: an ambiguous signal delivered by the scenario timeline, such
  as an unusual outbound byte count.
- **Finding**: evidence produced by a completed investigation. Findings are not
  placed on the timeline.
- **Hypothesis**: a public proposition the trainee may assess, such as data
  exfiltration or a legitimate backup transfer.
- **Investigation**: a public, author-defined kind of evidence-gathering work
  with eligible performer roles, prerequisites, matching hints, and a duration.
- **Investigation outcome**: the hidden, per-variant mapping from an
  investigation to one or more findings.
- **Assessment**: the trainee's current belief about a hypothesis, including
  confidence and any cited evidence that the acting role actually knows.

Reliability describes the trustworthiness of an observation or finding.
Confidence describes the trainee's belief in a hypothesis. They are deliberately
separate.

## Safety and determinism boundaries

```text
role question
    |
    v
role-scoped observations + findings ---> role-response LLM ---> validation
                                           (language only)

free-text investigation
    |
    v
application computes eligibility
    |
    v
eligible public definitions only ------> routing LLM ------> validation
    |
    v
application starts timer
    |
    v
variant outcome resolved only at completion
    |
    v
finding granted only to performer

free-text assessment
    |
    v
public hypotheses + actor knowledge ---> normalization LLM ---> validation
    |
    v
append-only assessment event; no truth comparison or grading
```

All LLM outputs use structured Pydantic schemas. IDs are checked against the
exact allow-list supplied in the request. A boundary violation causes one retry;
a second violation returns a safe fallback and writes an
`LLM_POLICY_VIOLATION` event.

The OpenAI adapter uses structured output through `responses.parse` with
`store=False`. Ollama uses native `/api/chat` with the same JSON schemas.
The fake provider is deterministic and is used by default and in tests.

Variant `ground_truth` and `investigation_outcomes` are excluded from runtime
serialization and are absent from every LLM request model. Public event listing
also redacts observation, finding, and evidence-share payloads. A role obtains
evidence through its role-scoped knowledge endpoint.

## Run with Docker

The default provider is deterministic and requires no model or API key:

```bash
docker compose up --build
```

Open:

- UI: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

The browser calls the frontend's same-origin `/api` path. Next.js proxies those
requests to the backend service, so the browser does not call port 8000 directly
and does not depend on cross-origin access.

### Ollama

Create or update `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_TIMEOUT_SECONDS=300
```

The URL must include `http://` and both slashes. Rebuild/recreate the backend
after changing provider environment variables:

```bash
docker compose up -d --build backend
```

The configured model must support the structured JSON responses used for role
responses, investigation routing, and assessment normalization.

### OpenAI

Set:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5-mini
```

Then rebuild/recreate the backend as shown above.

## Trainee walkthrough

Start Track Alpha and advance to the outbound-transfer observation:

```bash
curl -s http://localhost:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"scenario_id":"ransomware_001","variant_id":"track_alpha"}'
curl -X POST http://localhost:8000/sessions/SESSION_ID/start
curl -X POST http://localhost:8000/sessions/SESSION_ID/advance-time \
  -H 'content-type: application/json' \
  -d '{"minutes":45}'
```

Request an investigation in natural language. There is no investigation menu in
the trainee workflow:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/investigations \
  -H 'content-type: application/json' \
  -d '{
    "requester_role":"ciso",
    "performer_role":"soc",
    "request":"Find where that outbound traffic went."
  }'
```

The matched investigation takes five simulated minutes. It does not complete
from wall-clock time:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/advance-time \
  -H 'content-type: application/json' \
  -d '{"minutes":5}'
curl http://localhost:8000/sessions/SESSION_ID/investigations
curl http://localhost:8000/sessions/SESSION_ID/roles/soc/knowledge
```

For Track Alpha this investigation grants `FD004` to SOC. Running the same
public observations and request in Track Bravo grants `FD010`. Neither hidden
mapping is returned by the investigation endpoints.

Record an assessment in the trainee's own words:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/assessments \
  -H 'content-type: application/json' \
  -d '{
    "actor_role":"soc",
    "statement":"Data exfiltration is highly likely based on FD004."
  }'
curl http://localhost:8000/sessions/SESSION_ID/assessments
```

The response reports what was normalized, not whether it is correct. Submitting
another assessment for the same hypothesis appends to `history` and replaces
that hypothesis in `current`.

Share evidence explicitly:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/actions/share-evidence \
  -H 'content-type: application/json' \
  -d '{"from_role":"soc","to_role":"dpo","evidence_id":"FD004"}'
```

## API surface

```text
GET  /health
GET  /scenarios
GET  /scenarios/{id}
GET  /scenarios/{id}/authoring
PUT  /scenarios/{id}/authoring
GET  /scenarios/{id}/sources
PUT  /scenarios/{id}/sources

POST /sessions
GET  /sessions/{id}
POST /sessions/{id}/start
POST /sessions/{id}/advance-time
POST /sessions/{id}/complete

GET  /sessions/{id}/roles
GET  /sessions/{id}/external-entities
GET  /sessions/{id}/roles/{role_id}/knowledge
POST /sessions/{id}/ask

POST /sessions/{id}/investigations
GET  /sessions/{id}/investigations
POST /sessions/{id}/assessments
GET  /sessions/{id}/assessments

POST /sessions/{id}/actions/share-evidence
POST /sessions/{id}/actions/decision
GET  /sessions/{id}/events
GET  /sessions/{id}/evaluation
```

The deprecated `actions/share-fact` compatibility route remains temporarily
but accepts only IDs that exist in the new evidence model.

Decision categories remain broad labels such as containment, exfiltration, and
notification. The trainee enters the actual decision manually:

```json
{
  "actor_role": "ciso",
  "category": "containment",
  "decision": "Isolate the affected servers while preserving emergency access.",
  "confidence": null,
  "rationale": "Encryption is continuing and lateral movement remains possible."
}
```

Detailed evaluation becomes available only after the session is completed.

## Scenario authoring

Before an exercise, open **Scenario authoring** on the setup screen. The editor
uses forms rather than raw YAML. Sprint 1 sections cover:

- metadata and broad decision categories
- roles and communication styles
- external entities
- observations and findings
- public hypotheses
- investigations, matching phrases, performers, prerequisites, and duration
- observation timeline grants
- hidden ground truth and per-variant investigation outcomes
- migrated scoring rules

The complete document is staged and compiled before any live file is changed.
A failed validation leaves both files and the loaded registry unchanged.
Successful writes preserve existing ownership and permissions.

Each scenario directory has nine canonical files:

```text
scenario.yaml            metadata, duration, and decision categories
roles.yaml               role responsibilities and communication style
external_entities.yaml   external recipients and accepted communication types
evidence.yaml            observation and finding definitions
hypotheses.yaml          public propositions available for assessments
investigations.yaml      public definitions, routing hints, prerequisites, duration
timeline.yaml            deterministic observation grants
variants.yaml            hidden truth, overrides, and investigation outcomes
scoring.yaml             deterministic process and assessment timing rules
```

The compiler rejects, among other problems:

- missing files or unknown keys
- malformed or duplicate stable IDs
- observation/finding ID collisions
- unknown role, evidence, hypothesis, event, or investigation references
- invalid timeline events or events beyond scenario duration
- missing or duplicate per-variant investigation outcomes
- outcomes that reference anything other than findings
- malformed type-specific scoring rules
- invalid merged variant overrides

The included ransomware scenario intentionally presents the same ambiguous
observations in both tracks. Investigation results, not initial observations,
allow the trainee to distinguish attacker exfiltration from an approved backup.

## Backend development

Python 3.12 or newer is required:

```bash
python3 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
PYTHONPATH=backend .venv/bin/pytest -q
```

Run locally with SQLite:

```bash
cd backend
DATABASE_URL=sqlite+pysqlite:///./trainer.sqlite3 \
SCENARIOS_PATH=../scenarios \
../.venv/bin/uvicorn app.main:app --reload
```

Run migrations against PostgreSQL:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://trainer:trainer@localhost:5432/trainer \
../.venv/bin/alembic upgrade head
```

Sprint 1 uses the existing append-only event table, so it does not require a new
database migration.

## Tests

```bash
PYTHONPATH=backend .venv/bin/pytest -q
cd frontend
npm run build
```

The backend suite covers schema failures, source rollback, deterministic variant
resolution, logical-time boundaries, exactly-once completion, prerequisites,
non-repeatability, role isolation, explicit sharing, divergent outcomes,
assessment revision, scoring migration, LLM validation/retry/fallback, provider
contracts, API redaction, and end-to-end discovery.

## Current limitations

- There is no authentication or separation between scenario authors, trainers,
  and trainees. The authoring API exposes hidden variant truth by design and
  must be restricted to a trusted network.
- The UI currently lets one operator act for all internal roles.
- Investigation routing and assessment normalization depend on model quality.
  Validation prevents unauthorized IDs, but a poorly matched eligible request
  can still require clearer trainee wording.
- Scenario definitions are filesystem-backed. Editing a scenario while sessions
  are active can change how those sessions materialize on their next command.
- External entities are authored and listed but outbound communication actions
  are not part of this sprint.
- The compatibility `share-fact` route is temporary and should be removed after
  all clients migrate to `share-evidence`.
