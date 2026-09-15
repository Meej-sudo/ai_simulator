# AI Incident Trainer POC

A modular-monolith proof of concept for organizational cyber-incident exercises. The simulation is deterministic; an LLM is used only to render a role's permitted knowledge as natural language.

## What is implemented

- YAML scenario compiler with strict Pydantic validation and cross-reference checks
- Browser-based form editor that abstracts and validates all six YAML scenario files
- Deterministic variant materialization with ground truth kept out of public API and LLM requests
- Logical simulation clock and interval-based timeline processing
- PostgreSQL/SQLAlchemy session state plus an append-only audit event log
- Event-replayed per-role knowledge and explicit `share_fact` transfers
- Structured per-role personalities with behavioral guidance under pressure
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

## System operation and information access

### Components and data flow

```text
Browser
  | HTTP to :3000; same-origin /api requests
  v
Next.js frontend
  | server-side rewrite to http://backend:8000
  v
FastAPI backend ---------------------------------> OpenAI or Ollama
  |                                                  role prompt, current role facts,
  |                                                  and the trainee's question only
  +----> in-memory scenario registry
  |      roles, facts, timelines, variants,
  |      hidden ground truth, and scoring rules
  |
  +----> PostgreSQL
         sessions and ordered audit events
```

At startup, the backend reads and validates the YAML files under `scenarios/` and
keeps the compiled scenario catalog in memory. The Docker deployment mounts that
directory read-write so the scenario-authoring endpoints can persist validated
changes. PostgreSQL stores session state and the event history; it does not store
the scenario definitions themselves.

The normal exercise flow is:

1. The frontend lists public scenario metadata, variants, decision categories,
   and role descriptions, then creates and starts a session.
2. Advancing the logical clock fires due timeline events. Each grant produces a
   `FACT_LEARNED` event for one role.
3. Current knowledge is reconstructed by replaying that role's `FACT_LEARNED`
   events through the current simulation time. Facts are therefore not globally
   known merely because they exist in `facts.yaml`.
4. Sharing a fact is a controlled state transition. The service verifies that
   the sending role currently knows the fact, records `FACT_SHARED`, and grants
   it to the receiving role with another `FACT_LEARNED` event.
5. Asking a role causes the backend to assemble an LLM request from that role's
   identity, guidance, current facts, confidence levels, the current time, and
   the trainee's question. Other roles' facts, future timeline grants, scoring
   rules, and variant ground truth are not added to the request.
6. The LLM must return a structured response. The backend rejects references to
   fact IDs outside the allowed set and rejects permitted internal fact IDs when
   they appear in the displayed message. It retries once and then returns a
   fixed safe fallback if the output still violates those checks. Successful
   questions, responses, violations, shares, decisions, and time changes are
   recorded as audit events.
7. Decisions are free text plus a scenario-defined category and optional
   confidence. Scoring is performed by deterministic code over the event log,
   not by the LLM. Detailed evaluation is unavailable until the session has
   been completed.

For the included ransomware scenario, the authored visibility schedule is:

| Simulated role | Facts learned directly from the timeline |
| --- | --- |
| SOC analyst | Ransomware activity at T+5, failed admin logins at T+10, suspected account compromise at T+25, and the exfiltration assessment and outbound-traffic observation at T+45. Track Alpha adds confirmed exfiltration at T+80. Track Bravo instead identifies the traffic as approved backup activity at T+55. |
| CISO | Suspected account compromise and ransomware activity at T+40. |
| DPO | No direct timeline grants; learns facts only when another role explicitly shares them. |
| CEO | No direct timeline grants; learns facts only when another role explicitly shares them. |

The schedule controls a persona's derived knowledge and LLM context. It does not
prevent the facilitator UI from retrieving each persona's knowledge, as described
below.

### What is restricted

| Information or action | Current restriction |
| --- | --- |
| Variant ground truth | Remains in the backend's scenario object and is excluded from public response models and LLM requests. It is still visible to operators who can read the scenario files, container, or host filesystem. |
| Future facts | Do not enter role knowledge until their timeline event fires. They are not sent to the LLM, although an operator with filesystem access can read the authored scenario. |
| Another role's unshared facts | Excluded when generating a response for the target role. A fact enters another role's knowledge only through an explicit share or a timeline grant. |
| Fact sharing | The backend verifies that the declared sending role knows the fact and that both role and fact IDs exist. |
| LLM output | Must match the structured response schema. Referenced fact IDs are checked against the role's allowed set; violations cause one retry and then a safe fallback. |
| Evaluation | The endpoint returns a conflict response until the session is completed. The UI also withholds the score during an active exercise. |
| Session mutation | Start, advance, ask, share, decide, and complete operations are constrained by session state and validated request schemas. Completed sessions reject further exercise commands. |
| Database access | PostgreSQL is available to the backend on the Compose network and is not published as a host port by the supplied Compose file. |
| Scenario modification | The authoring and source endpoints validate complete updates, write them atomically, and reload the in-memory registry. The scenario directory is mounted read-write in Docker. |
| OpenAI retention request | The OpenAI adapter requests `store=False`. The selected provider still receives the role prompt, permitted facts, and trainee question and remains subject to that provider's processing and logging controls. |

These are simulation and application-state boundaries. They are not user or
tenant authorization boundaries.

### Current trust model and access limitations

This POC assumes a trusted facilitator or a trusted single-user environment. It
does **not** implement login, user accounts, session ownership, participant-role
assignment, API keys, or role-based access control. A role such as `soc` or
`ciso` is a persona supplied in a request, not the identity of the caller.

Consequences of the current design include:

- Any client that can reach the API can create sessions. Anyone who obtains a
  session UUID can read that session, advance or complete it, ask any role a
  question, record a decision as any role, or initiate a valid fact share.
- Any client that can reach the authoring API can read scenario ground truth and
  submit validated changes to the scenario files. There is no separate author
  identity or permission check.
- `GET /sessions/{id}/roles/{role_id}/knowledge` has no caller authorization.
  The frontend intentionally fetches every role's knowledge so it can populate
  the facilitator's sharing controls. This means role-specific knowledge is
  isolated from the role-response LLM context, but not from the human using the
  browser or from a direct API client.
- `GET /sessions/{id}/events` returns the complete event objects and payloads.
  Those payloads can contain trainee questions, role responses, decisions,
  rationales, fact IDs, and LLM-policy violation details. The UI shows only a
  summary, but hiding fields in the UI is not an access control.
- The evaluation time gate is state-based, not identity-based. Any API caller
  able to complete a session can then retrieve its detailed evaluation.
- CORS allows browser cross-origin calls from `http://localhost:3000`, but CORS
  is not authentication and does not stop non-browser clients. In Compose, the
  backend is also published directly on host port `8000`, including its OpenAPI
  documentation, while the frontend is published on port `3000`.
- The supplied HTTP services have no TLS termination. Network confidentiality
  must be provided by the deployment environment or a reverse proxy.
- The event history is append-only through the application repository and there
  are no update/delete API routes, but it is not cryptographically tamper-evident.
  A database administrator can alter records. Free-text questions, answers,
  decisions, and rationales persist in the database volume.
- LLM validation checks declared fact references and exposure of permitted
  internal IDs; it does not detect an arbitrary unknown ID appearing only in
  prose or prove that every natural-language claim is semantically supported by
  the permitted facts. Prompt instructions, structured references, retry, and
  fallback reduce leakage risk but are not a complete information-flow security
  mechanism.
- Secrets such as `OPENAI_API_KEY` are passed only to the backend, not embedded
  in the browser bundle. They are still plain environment variables visible to
  users or processes with sufficient Docker/host access. The example database
  credentials are development defaults and should not be used in production.

For multi-user or untrusted deployment, put the services behind TLS, stop
publishing the backend directly, add authentication and per-session membership,
authorize every read and mutation against the caller's assigned role, separate
facilitator-only event/evaluation APIs from participant APIs, return only the
caller's knowledge, protect secrets with the deployment's secret manager, and
define retention/redaction controls for audit payloads. The semantic validation
of LLM answers should also be strengthened if role separation is a security
requirement rather than a training-game rule.

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

Before starting an exercise, select a scenario and open **Edit scenario** from the
setup screen. The editor presents guided forms for the overview, roles, facts,
timeline, variants, and scoring rules; users do not need to understand YAML. It
also updates references when IDs are renamed and uses constrained controls for
roles, facts, events, categories, confidence values, and scoring rule types.

The structured document is saved through the authoring API and rendered back to
the six YAML files. The backend compiles a staged copy first; invalid values,
renamed scenario IDs, or broken cross-references return a validation error without
changing the live files. Successful changes are reloaded immediately for new
exercises. The lower-level source API remains available for advanced integrations.

The editor exposes scenario ground truth and this POC does not yet provide user
authentication or author/trainee permissions. Deploy the authoring surface only on
a trusted network until access control is added, and do not edit a scenario while
another user is actively running it.

Each scenario directory contains:

```text
scenario.yaml   metadata and duration
roles.yaml      role identity, responsibilities, personality, and style
facts.yaml      stable observable/assessment fact definitions
timeline.yaml   deterministic knowledge grants at relative minutes
variants.yaml   isolated ground truth and deterministic overrides
scoring.yaml    deterministic scoring rules
```

The compiler rejects duplicate IDs, unknown roles/facts/events, events beyond the scenario duration, malformed type-specific scoring rules, and invalid merged variant overrides. The included `ransomware_001` scenario has four roles and two neutral public tracks whose hidden exfiltration outcomes differ.

Each role personality combines a compact Big Five trait profile with concrete
behavioral tendencies and an under-pressure response. Personality affects how a
role communicates and frames its permitted knowledge; it cannot add facts,
change confidence, expand authority, or override the knowledge boundary.

## Tests

```bash
cd backend
../.venv/bin/pytest -q
```

The suite covers compiler failures, validated/rollback-safe source editing,
deterministic variant resolution, logical time boundaries, knowledge isolation and
transfer, evaluation, and the LLM boundary retry/fallback behavior.
