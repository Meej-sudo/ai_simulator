# Messenger UI — implementation brief

You are implementing a UI and API redesign of this repository (`ai_simulator`, branch
`updated_gamee_logic`). A visual reference mockup is at `docs/ui/incident-room-mockup.html`
— open it and read its markup before starting. It is a static prototype, not code to copy.

Work through the stages **in order**. After each stage, run the verification commands and
**stop for review before starting the next stage.** Do not attempt the whole brief in one pass.

---

## Context: what problem this solves

The trainee currently has no identity in the system. Every action form re-asks who is acting:

```
ask          → target_role
investigate  → requester_role + performer_role
assess       → actor_role
share        → from_role + to_role + evidence_id
decide       → actor_role + category + confidence
```

Twelve `<select>` elements across five forms in `frontend/app/page.tsx`. The fix is to seat the
trainee in one role for the session. Then `actor_role` comes from the seat, `target_role` comes
from whichever conversation thread is open, and the UI becomes a messenger.

---

## Invariants — do not break these

1. **The LLM never decides anything.** It renders role language, routes investigation requests,
   and normalizes assessments. It does not resolve outcomes, advance time, reveal evidence, or
   grade. Do not add an LLM call that does any of those.
2. **Variant ground truth and `investigation_outcomes` never enter an LLM request or a public
   response model.** `backend/tests/test_api.py` asserts this. Keep it true.
3. **Role knowledge stays derived, not stored.** `KnowledgeEngine.get_role_knowledge` replays the
   event log. Do not introduce a denormalized "what this role knows" table.
4. **New state goes in the event log**, not in new mutable columns, unless the brief says otherwise.
   Follow the existing projection pattern in `SimulationService.investigations()` and
   `SimulationService.assessments()`.
5. **Determinism.** Given the same events, every projection and every score must be identical.
6. Existing tests must keep passing. When a test's premise genuinely changes, update it in the
   same commit and say so.

## Do not touch in this brief

- `backend/app/domain/scenarios/compiler.py` and the scenario YAML schema
- `frontend/app/ScenarioForm.tsx`, `ScenarioEditor.tsx`, `ModelConfiguration.tsx`
- The evaluation/scoring engine (a separate piece of work fixes its flaws)
- Alembic revisions 0001 and 0002

---

## Stage 0 — Orient

Read, in this order:

- `backend/app/services/simulation.py`
- `backend/app/domain/simulation/models.py` (the `EventType` enum especially)
- `backend/app/domain/knowledge/engine.py`
- `backend/app/api/routes.py` and `backend/app/schemas/api.py`
- `backend/app/llm/models.py`, `prompts.py`, `validation.py`
- `frontend/app/page.tsx`
- `docs/ui/incident-room-mockup.html`

Establish a baseline:

```bash
python3 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
PYTHONPATH=backend .venv/bin/pytest -q          # expect 56 passed
cd frontend && npm ci && npx tsc --noEmit
```

Report the baseline before continuing.

---

## Stage 1 — Fix the event sequence race

Do this first. The messenger UI is far chattier than the current one and will hit this.

`SessionRepository.append_event` in `backend/app/repositories/sessions.py` does
`SELECT max(sequence)` then `INSERT`, with no lock, against a table carrying
`UniqueConstraint("session_id", "sequence")`. Two concurrent requests on one session collide.

Fix it. Preferred approach: lock the session row before computing the next sequence
(`SELECT ... FOR UPDATE` on `simulation_sessions` where supported), and fall back to catching
`IntegrityError` and retrying with a recomputed sequence, bounded to a few attempts. It must work
on both PostgreSQL and SQLite, since the tests use SQLite.

**Verify:** add `backend/tests/test_event_sequencing.py` proving that concurrent `append_event`
calls against one session produce a contiguous gap-free sequence with no exception.

---

## Stage 2 — Session seats (backend)

**Schema.** Add `seat_role: str | None` to `SessionRecord` in `backend/app/models/database.py`.
Create Alembic revision `0003_session_seat` (down-revision `0002_session_scenario_snapshot`),
nullable so existing sessions survive.

**Creation.** `CreateSessionRequest` in `backend/app/schemas/api.py` gains an optional
`seat_role`. `SimulationService.create_session` validates it against the compiled scenario's
roles and raises `NotFoundError` if unknown. `SessionResponse` returns it. Sessions created
without a seat keep today's behaviour exactly.

**Default the actor.** These service methods currently take an explicit actor and must now accept
`None` and fall back to the session seat, raising `InvalidOperationError` if there is neither:

- `record_assessment(actor_role=None)`
- `make_decision(actor_role=None)`
- `request_investigation(requester_role=None)`
- `share_evidence(from_role=None)`

Make the corresponding request schema fields optional. Do not remove them — the facilitator
console in Stage 6 still needs to act as any role.

**Seat view.** Add `GET /sessions/{id}/me` returning the seat role's identity plus its knowledge,
reusing `RoleKnowledge`. This is what the trainee client calls. It must not expose any other
role's knowledge.

**Verify:** tests covering seat validation on creation, actor defaulting for all four methods,
the error when neither is supplied, and that `/me` on a seatless session returns 409.

---

## Stage 3 — Threads and messages

Threads are a **projection over the event log**, not new storage. Follow the shape of
`SimulationService.investigations()`.

**Thread identity.** Two kinds, addressed by string id:

- `channel:bridge` — all roles participating in the scenario
- `dm:<role_id>` — the seat and one other role

**New event type.** Add `MESSAGE_POSTED` to `EventType` with payload:

```python
{"thread_id": str, "text": str, "cited_evidence_ids": list[str]}
```

`actor_role` is the sender. Posting is a new service method `post_message(session_id, thread_id,
text, cited_evidence_ids, actor_role=None)` which:

1. resolves the actor from the seat,
2. validates every cited evidence id is currently known to the actor (reuse the existing check in
   `share_evidence`; reject with `InvalidOperationError` otherwise),
3. appends `MESSAGE_POSTED`,
4. fans out one `EVIDENCE_SHARED` event per (cited evidence × recipient), where recipients are the
   thread's other participants. A DM shares with one role; the bridge shares with all.

This keeps `EVIDENCE_SHARED` as the single source of truth for who learned what, so
`KnowledgeEngine` needs no changes at all. Confirm that before writing code.

**Endpoints.**

- `GET /sessions/{id}/threads` — for the seat: every thread it participates in, with display name,
  participant roles, the last message preview, and an unread count (messages after the seat's last
  `MESSAGE_POSTED` in that thread).
- `GET /sessions/{id}/threads/{thread_id}/messages` — ordered items the seat is allowed to see.

**Visibility rule for the messages projection.** Include only:

- `MESSAGE_POSTED` in this thread
- `QUESTION_ASKED` / `ROLE_RESPONDED` where the thread's other role is the target, and the seat asked
- `EVIDENCE_SHARED` where the seat is sender or recipient
- `DECISION_MADE` / `ASSESSMENT_RECORDED` by the seat
- `INVESTIGATION_STARTED` / `INVESTIGATION_COMPLETED` where the seat is requester or performer
- `TIMELINE_EVENT_TRIGGERED` and `OBSERVATION_REVEALED` where the seat is the target role, rendered
  as system items on `channel:bridge`

Everything else is excluded. Never leak another role's private exchange into the seat's view.

**Verify:** tests that a DM between two other roles is invisible to the seat; that posting to
`channel:bridge` with a citation grants that evidence to every participant while a DM grants it to
exactly one; that citing evidence the actor does not hold is rejected; that unread counts are
correct.

---

## Stage 4 — Conversation memory in the role contract

A messenger UI implies continuity. Today `RoleResponseRequest` carries only the current question,
so "what about that?" fails.

In `backend/app/llm/models.py`:

```python
class ThreadTurn(BaseModel):
    speaker: Literal["trainee", "role"]
    text: str
    simulation_time: int

class RoleResponseRequest(BaseModel):
    ...
    thread_history: list[ThreadTurn] = []
```

Build the history in `SimulationService._ask_role` from `QUESTION_ASKED` / `ROLE_RESPONDED` events
scoped to **this seat and this target role only**, most recent first, capped at 6 turns, then
reversed into chronological order. Truncate oldest-first.

This is safe: the history is the role's own prior exchange, so it contains nothing the role did not
already know. Do not widen it beyond one thread.

In `backend/app/llm/prompts.py`, render it in `build_system_prompt` under a
`CONVERSATION SO FAR` section placed **before** `CURRENT ROLE-SCOPED EVIDENCE`, so the evidence
boundary is the last instruction the model reads. Keep the existing prohibitions verbatim.

Leave `ConstrainedRoleResponder` unchanged — the allow-list check still derives from
`permitted_observations` and `permitted_findings` only.

**Verify:** tests that history is capped at 6 turns, is scoped to one target role, is chronological,
is empty on a first message, and that the existing leakage tests in `test_llm_validation.py` still
pass unchanged.

---

## Stage 5 — Frontend rebuild

`frontend/app/page.tsx` is 788 lines with ~35 `useState` hooks. Do not extend it. Replace it.

**Structure:**

```
frontend/app/
  page.tsx                 launch screen: scenario, variant, seat picker
  session/
    SessionView.tsx        three-pane shell
    TopBar.tsx             scenario, T+ clock, advance controls, seat identity
    ThreadRail.tsx         pending demands, channels, DMs, unread dots
    Conversation.tsx       message stream
    Composer.tsx           mode tabs, evidence citation chips, textarea
    ContextRail.tsx        seat's evidence, work in flight, own assessments
    useSession.ts          single useReducer for all session state
    types.ts
```

**Rules:**

- One `useReducer` in `useSession.ts`. No component holds more than local input state.
- Delete every hardcoded role id. `"soc"`, `"ciso"`, `"dpo"`, `"containment"` must not appear as
  defaults anywhere. Derive from the loaded scenario and the chosen seat.
- The seat picker on the launch screen lists roles from `GET /scenarios/{id}`.
- **The trainee client must never call `/sessions/{id}/roles/{role}/knowledge` for a role other
  than the seat.** It calls `/sessions/{id}/me`. The current all-roles fetch is the leak this
  redesign removes.

**Composer modes** map to endpoints:

| Mode | Endpoint |
|---|---|
| Message | `POST /sessions/{id}/threads/{thread}/messages` |
| Request work | `POST /sessions/{id}/investigations` |
| Log assessment | `POST /sessions/{id}/assessments` |
| Log decision | `POST /sessions/{id}/actions/decision` |

Switching mode changes the placeholder and the hint line under the composer. Evidence citation
chips stay available in every mode; in Message mode they share evidence, in assessment mode they
become the cited basis.

**Message rendering.** Speech renders as bubbles (own messages right-aligned with the green
accent, others left). Assessments, decisions, investigations and demands render as bordered record
cards with a coloured left edge, visually distinct from speech, because those are the audit-relevant
acts and must stay findable in a long scroll. Match `docs/ui/incident-room-mockup.html`.

**Keep** the existing ndjson streaming in `frontend/app/api.ts` — `streamApi` and the
`/ask/stream` endpoint work well and transfer to this layout unchanged. Do **not** add typing
indicators, read receipts, or anything implying wall-clock time; the clock only moves when the
trainee advances it.

Reuse the palette and type tokens already in `frontend/app/styles.css`.

**Verify:** `npx tsc --noEmit` clean, `npm run build` succeeds, and
`grep -rn '"soc"\|"ciso"\|"dpo"\|"containment"' frontend/app` returns nothing outside test fixtures.

---

## Stage 6 — Split the facilitator console

The trainee client and the facilitator need opposite things. Separate them.

Move these behind a `/facilitator` route prefix in `backend/app/api/routes.py`:

- `GET /facilitator/sessions/{id}/roles/{role_id}/knowledge` (any role)
- `GET /facilitator/sessions/{id}/events` (full log)
- `GET /facilitator/sessions/{id}/evaluation`

Keep the old paths as deprecated aliases for one release, marked `deprecated=True` like the
existing `share-fact` route.

While moving `/events`: the current partial redaction in `SimulationService.events()` is
misleading. It redacts `OBSERVATION_REVEALED`, `FINDING_REVEALED` and `EVIDENCE_SHARED` while
`ROLE_RESPONDED` still carries `referenced_evidence_ids` and the full prose, and
`ASSESSMENT_RECORDED` still carries `basis_evidence_ids`. On the facilitator route, drop the
redaction entirely — the facilitator is meant to see everything. Update the docstring and the
README section to say so plainly rather than implying a boundary that is not enforced.

Add `frontend/app/facilitator/page.tsx`: a per-role knowledge matrix, the raw event log, the
clock controls, and session completion. Plain and dense. It is an operator tool, not a trainee
experience.

**Verify:** a test asserting the trainee-facing routes never return another role's evidence, and
that the facilitator routes do.

---

## Definition of done

- `PYTHONPATH=backend .venv/bin/pytest -q` passes, with new tests for each stage
- `cd frontend && npx tsc --noEmit && npm run build` clean
- `docker compose up --build` runs an exercise end to end: pick scenario, variant and seat; message
  a role in a DM; post to the bridge citing evidence and see it reach the other participants;
  request an investigation in free text; advance time and watch the finding arrive; log an
  assessment and a decision; complete and read the evaluation
- No hardcoded role ids in the frontend
- README updated: seats, threads, the trainee/facilitator split, and the honest description of what
  `/events` exposes

## Out of scope, do not start

- Scoring rework (`avoid_premature_assessment` currently awards points for inaction, and nothing
  scores conclusion correctness against variant ground truth)
- Demands, support ceilings, and calibration scoring
- Authentication and per-seat authorization — these routes are still unauthenticated, which is why
  the README's trust-model section must stay accurate

---

## Working agreement

- One stage per commit, with its tests.
- Edit files in place. Do not rewrite a file wholesale when a targeted change will do.
- If a stage turns out to need a change to something in the "do not touch" list, stop and explain
  rather than proceeding.
- If any invariant above conflicts with the brief, the invariant wins. Say so and stop.
