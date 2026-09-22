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
- Ambiguous event observations that do not reveal the scenario answer
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
- Versioned two-file scenario packages, shared participant catalogs, and strict
  Pydantic/cross-reference validation
- Immutable compiled scenario snapshots pin every new session to the content it
  started with
- Deterministic fake, OpenAI, and Ollama LLM adapters
- External entities retained as an existing extension for authorities, police,
  media, and other communication recipients

## Core concepts

- **Observation**: an ambiguous signal delivered by scenario events, such
  as an unusual outbound byte count.
- **Finding**: evidence produced by a completed investigation. Findings are not
  scheduled as events.
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

Variant `ground_truth` and `investigation_outcomes` are excluded from public
runtime serialization and are absent from every LLM request model. Public event
listing also redacts observation, finding, and evidence-share payloads. A role obtains
evidence through its role-scoped knowledge endpoint.

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
  |      roles, facts, events, variants,
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
2. Starting the session also starts its persisted real-time clock. The frontend
   synchronizes it every ten seconds, while `+5` and `+15` remain available as
   manual jumps. Every crossed minute uses the same deterministic event pipeline.
3. Current knowledge is reconstructed by replaying that role's `FACT_LEARNED`
   events through the current simulation time. Facts are therefore not globally
   known merely because they exist in `facts.yaml`.
4. Sharing a fact is a controlled state transition. The service verifies that
   the sending role currently knows the fact, records `FACT_SHARED`, and grants
   it to the receiving role with another `FACT_LEARNED` event.
5. Asking a role causes the backend to assemble an LLM request from that role's
   identity, guidance, current facts, confidence levels, the current time, and
   the trainee's question. Other roles' facts, future event grants, scoring
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

| Simulated role | Facts learned directly from scheduled events |
| --- | --- |
| SOC analyst | Ransomware activity at T+5, failed admin logins at T+10, suspected account compromise at T+25, and the exfiltration assessment and outbound-traffic observation at T+45. Track Alpha adds confirmed exfiltration at T+80. Track Bravo instead identifies the traffic as approved backup activity at T+55. |
| CISO | Suspected account compromise and ransomware activity at T+40. |
| DPO | No direct event grants; learns facts only when another role explicitly shares them. |
| CEO | No direct event grants; learns facts only when another role explicitly shares them. |

The schedule controls a persona's derived knowledge and LLM context. It does not
prevent the facilitator UI from retrieving each persona's knowledge, as described
below.

### What is restricted

| Information or action | Current restriction |
| --- | --- |
| Variant ground truth | Remains in the backend's scenario object and is excluded from public response models and LLM requests. It is still visible to operators who can read the scenario files, container, or host filesystem. |
| Future facts | Do not enter role knowledge until their scheduled event fires. They are not sent to the LLM, although an operator with filesystem access can read the authored scenario. |
| Another role's unshared facts | Excluded when generating a response for the target role. A fact enters another role's knowledge only through an explicit share or an event grant. |
| Fact sharing | The backend verifies that the declared sending role knows the fact and that both role and fact IDs exist. |
| LLM output | Must match the structured response schema. Referenced fact IDs are checked against the role's allowed set; violations cause one retry and then a safe fallback. |
| Evaluation | The endpoint returns a conflict response until the session is completed. The UI also withholds the score during an active exercise. |
| Session mutation | Start, advance, ask, share, decide, and complete operations are constrained by session state and validated request schemas. Completed sessions reject further exercise commands. |
| Database access | PostgreSQL is available to the backend on the Compose network and is not published as a host port by the supplied Compose file. |
| Scenario modification | The authoring and source endpoints validate complete updates, write them atomically, and reload the in-memory registry. The scenario directory is mounted read-write in Docker. |
| AI model configuration | Ollama models are discovered through the backend. A saved provider/model pair is written atomically to `.llm-config/.env` and replaces the in-memory provider. The UI prevents exercise launch while no model is configured. |
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
- Any client that can reach the model-settings API can discover Ollama models
  and change the provider/model used for subsequent prompts. Keep this
  administrative surface on a trusted network.
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

Start the application without a preselected model:

```bash
docker compose up --build
```

The short commit hash of the build is shown in the corner of every page. It is
read from `.git` while the frontend image is built; the runtime image does not
contain `.git`. To hide it, build with:

```bash
SHOW_BUILD_COMMIT=false docker compose up --build
```

Nothing is shown when the hash is switched off or the source is not a git
checkout.

Open:

- UI: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

The browser calls the frontend's same-origin `/api` path. Next.js proxies those
requests to the backend service, so the browser does not call port 8000 directly
and does not depend on cross-origin access. The backend container applies Alembic
database migrations before starting the API. It safely adopts databases created by
the original pre-Alembic container before applying newer revisions.

For Ollama, copy `.env.example` to `.env` and set the URL of the Ollama server:

```env
OLLAMA_BASE_URL=http://your-ollama-host:11434
OLLAMA_DISCOVERY_TIMEOUT_SECONDS=10
OLLAMA_TIMEOUT_SECONDS=300
```

Open **AI model configuration** on the setup page. Choosing Ollama automatically
discovers its installed models. Save one before starting an exercise. The active
provider and model are applied immediately and written to `.llm-config/.env`, which
is host-mounted into the backend and survives container restarts. The file is
runtime state and is intentionally excluded from Git.

No provider or model is selected by default. Until a model is saved, the setup
page displays a warning, disables **Start exercise**, and the backend rejects new
sessions and role prompts with a configuration error. Ollama is the first provider
exposed through this UI; the existing OpenAI adapter remains available for future
configuration support.

The Ollama adapter calls the native `/api/chat` endpoint with a JSON schema for
each structured contract (`RoleResponse`, investigation interpretation, and
assessment interpretation). Responses still go through the same knowledge-boundary
validation, retry, safe fallback, and audit logging as the other providers. The
exercise UI uses `/sessions/{id}/ask/stream`, which releases the reply while it is
still being generated. The provider streams one structured JSON object, and the
backend decodes the `message` field out of that partial document, forwarding each
newly completed piece of prose as a newline-delimited `delta` event. The warmup
cursor shows until the first one arrives and is removed on completion.

Two rules keep early release safe. Text stops being released the moment an
internal evidence ID appears in it, because such a reply will be rejected and
retried. A retry is never appended to what the trainee already saw: when the
validated message differs from the text that was streamed, the endpoint sends a
`replace` event carrying the validated message and the UI shows that instead.
Structured fields, the evidence-boundary checks, the single retry, and the safe
fallback are unchanged, and the completion event still carries the validated
references and certainty.

The configured model must support the structured JSON responses used for role
responses, investigation routing, and assessment normalization.

### Model preloading

A remote Ollama server unloads a model a few minutes after its last request,
which makes the first question of an exercise slow. Starting an exercise sends
a load request (`POST /api/generate` with only the model and the same options
the chat requests use), and a heartbeat repeats it whenever nothing has reached
Ollama for four minutes. Both are fire-and-forget: a slow or failed load never
blocks the exercise or fails a request.

`keep_alive` is never sent, so the server's own unload timer applies unchanged.
The heartbeat stops once nothing has used the model for thirty minutes, and the
server then unloads it normally. Set `OLLAMA_KEEP_WARM=false` to switch the
whole behaviour off. Only the Ollama provider is affected.

Check what the server currently holds loaded with `curl "$OLLAMA_URL/api/ps"`:
the model should appear once an exercise starts, with `expires_at` moving
forward about every four minutes while the exercise stays open.

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

The session clock runs automatically after `start`. Polling preserves its
sub-minute remainder, so ten-second synchronization does not discard elapsed
seconds. These endpoints can also be used by another client:

```bash
curl -X POST http://localhost:8000/sessions/SESSION_ID/clock/sync
curl -X POST http://localhost:8000/sessions/SESSION_ID/clock/pause
curl -X POST http://localhost:8000/sessions/SESSION_ID/clock/resume
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

The matched investigation takes five simulated minutes. It completes through
normal clock synchronization or an optional manual jump:

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
POST /sessions/{id}/clock/sync
POST /sessions/{id}/clock/pause
POST /sessions/{id}/clock/resume
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
GET  /sessions/{id}/interactions
POST /sessions/{id}/interactions/{interaction_id}/respond
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
- generic deterministic event triggers, evidence effects, passive organizational
  pressure, stakeholder objectives, and follow-ups
- hidden ground truth and per-variant investigation outcomes
- migrated scoring rules

Events are strongly typed and deterministic. Supported triggers are
`simulation_time`, `assessment_exists`, `evidence_known`, `decision_recorded`,
`communication_sent`, `event_fired`, `all`, and `any`. Reveal events apply typed
knowledge effects. Organizational-pressure events select an internal role or an
external entity and publish an authored demand to the incident bridge without
opening a chat or calling the model. Stakeholder events select an actor role and
an authored objective. The configured model only turns that objective into wording
using the actor's current knowledge. It never decides whether an event fires.

```yaml
events:
  - id: E019
    type: organizational_pressure
    trigger:
      type: simulation_time
      at_minute: 40
    source:
      kind: role
      id: ceo
    pressure:
      category: operational_restoration
      severity: high
      message: Leadership asks when customer-facing services can be restored.
    once: true

  - id: E020
    type: stakeholder_interaction
    trigger:
      type: assessment_exists
      hypothesis_id: H002
      minimum_confidence: medium
    actor_role: ceo
    interaction:
      objective: Obtain a concise executive assessment of possible data exfiltration.
      context:
        - Ask what is known versus suspected.
    once: true
```

Stakeholder requests appear in the incident-room rail. The external trainee can
open them, answer in free text, receive an authored deterministic follow-up, and
see when the interaction is resolved. Responses and their contemporaneous
knowledge snapshots are retained in the append-only event log but are not scored.

The complete document is staged and compiled before any live file is changed.
A failed validation leaves both files and the loaded registry unchanged.
Successful writes preserve existing ownership and permissions.

Scenario content uses schema version 2 and this layout:

```text
content/
  catalogs/
    roles.yaml                 reusable internal roles (responsibilities, personality, style)
    external_entities.yaml     reusable external recipients
  scenarios/
    <scenario_id>/
      definition.yaml          scenario, participants, evidence, events, and scoring
      variants.yaml            hidden truth, overrides, and investigation outcomes
```

Participant roles are exclusively catalog references. Role definitions are stored
once in `content/catalogs/roles.yaml`, and scenarios contain only their IDs:

```yaml
participants:
  roles:
    - soc
    - dpo
    - exercise_observer
```

The form editor presents the resolved role definitions. Adding or editing a role
updates the shared catalog, so the change applies to every scenario that references
that ID. Removing a role in the scenario editor removes only its participation and
does not delete the catalog entry. Scenario and catalog changes are validated and
published together with rollback on failure. Raw source editing accepts exactly
`definition.yaml` and `variants.yaml`.

The compiler rejects, among other problems:

- missing files or unknown keys
- malformed or duplicate stable IDs
- observation/finding ID collisions
- unknown role, evidence, hypothesis, event, or investigation references
- invalid events or events beyond scenario duration
- missing or duplicate per-variant investigation outcomes
- outcomes that reference anything other than findings
- malformed type-specific scoring rules
- invalid merged event or observation overrides

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
SCENARIOS_PATH=../content/scenarios \
../.venv/bin/uvicorn app.main:app --reload
```

Run migrations against PostgreSQL:

```bash
cd backend
DATABASE_URL=postgresql+psycopg://trainer:trainer@localhost:5432/trainer \
../.venv/bin/alembic upgrade head
```

Schema version 2 adds immutable scenario data to session records. Version 3 adds
the persisted clock state used for automatic advancement and pause/resume. Docker
applies migrations automatically; local deployments must run `alembic upgrade head`
before starting the updated API. New sessions retain their compiled scenario and
variant snapshot even if authors edit the source files later.

Legacy nine-file bundles remain readable so deployments can migrate gradually. To
convert them without modifying or deleting the original files, run:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_scenarios_v2.py \
  path/to/legacy-scenarios content/scenarios --catalogs content/catalogs
```

The command refuses to overwrite an existing destination and verifies that the
compiled legacy and v2 representations are identical before publishing each bundle.

Each role personality combines a compact Big Five trait profile with concrete
behavioral tendencies and an under-pressure response. Personality affects how a
role communicates and frames its permitted knowledge; it cannot add facts,
change confidence, expand authority, or override the knowledge boundary.

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
- Scenario definitions are filesystem-backed. New sessions are pinned to an
  immutable snapshot; sessions created before this migration use the legacy
  current-content fallback until they are replaced.
- External entities can originate passive organizational pressure, but outbound
  trainee communication actions are not part of this sprint.
- The compatibility `share-fact` route is temporary and should be removed after
  all clients migrate to `share-evidence`.
