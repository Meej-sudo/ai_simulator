# Unpushed Commit Review

## Overview

- **Current branch:** `fix/qa-bugs-and-improvements`
- **Upstream branch:** *none tracked* — the branch has no upstream configured. Its base is `origin/updated_gamee_logic` (merge-base `3e6c97a`), and it also descends from `origin/main` via that branch. The commits below are not reachable from any remote branch (`origin/main`, `origin/updated_gamee_logic`).
- **Number of unpushed commits:** 6
- **Commit range reviewed:** `3e6c97a..a4248cf` (oldest → newest: `60c35fe`, `27a73a2`, `f2210e4`, `fde3605`, `0758617`, `a4248cf`)
- **Overall summary:** These commits form a single QA-hardening cycle for the "incident room" simulation trainer. A QA pass produced bug reports (`fde3605`, later partly removed in `a4248cf`); the fixes were landed as a backend batch (`27a73a2`), a frontend batch (`f2210e4`), a data cleanup (`60c35fe`), and a follow-up batch from a second playthrough (`0758617`). Collectively they: remove a placeholder role from scenario data, add a session-listing endpoint, auto-complete sessions at the simulation time limit (later refined to clamp rather than error), make investigation rejections explanatory with actionable suggestions, add confidence warnings for assessments, harden streamed replies against interruption, add evidence sharing UI, live-poll events, restore running sessions after reload, and render a per-rule evaluation debrief.

> Note: the branch itself cannot be pushed as a fast-forward of any existing remote branch — pushing it will create a new remote branch (or a PR against `main`).

---

## Commit 1 — `60c35fe`
**Commit:** `60c35fefab2b7516bf94148301ad81f4e960893d`
**Message:** `Remove placeholder role_5 from scenario and catalog (BUG-1)`
**Date:** 2026-09-17 10:39:05 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
Deletes a leftover template/placeholder role (`role_5`, display name "New role") that had been accidentally shipped in the role catalog and referenced by the ransomware scenario, and updates the compiler tests to match.

### Changes

#### Change 1 — Remove placeholder role from the role catalog
- **What changed:** The entire `role_5` entry was deleted from `content/catalogs/roles.yaml` (18 lines). It was a boilerplate entry: display name "New role", placeholder responsibility text ("Describe this role's responsibility"), and all Big-Five personality traits set to `medium`.
- **Why:** This is clearly an artifact of the scenario editor creating a new role but never filling it in; QA tracked it as BUG-1. An LLM agent would have been instantiated with this empty persona during exercises.

#### Change 2 — Remove `role_5` from the scenario participants
- **What changed:** `content/scenarios/ransomware_001/definition.yaml` no longer lists `role_5` under `participants.roles` (now `soc`, `ciso`, `dpo`, `ceo`).
- **Behavior:** The scenario now starts with 4 roles instead of 5; no empty DM thread / agent is created for the placeholder.

#### Change 3 — Update compiler test expectations
- **What changed:** `backend/tests/test_scenario_compiler.py` — two assertions updated: the compiled role-id set and the round-trip serialization check for `definition["participants"]["roles"]` both dropped `"role_5"`.
- **Note:** Test-only change keeping the suite green; no compiler logic changed.

### Files Changed
- `content/catalogs/roles.yaml` — removed `role_5` entry.
- `content/scenarios/ransomware_001/definition.yaml` — removed `role_5` from participants.
- `backend/tests/test_scenario_compiler.py` — updated expected role sets (2 assertions).

### Technical Notes
- Pure content/data change plus test expectation updates; no code paths modified.
- Backward compatibility: any *already-created* session in a database that snapshotted the old scenario definition would still contain `role_5`. Since sessions store a scenario snapshot (`0002_session_scenario_snapshot.py` migration exists), old sessions in persisted stores could still show the placeholder role. Not a problem for ephemeral/test databases.

### Potential Issues / Things to Review
- No migration or cleanup for pre-existing sessions that snapshot `role_5` (likely fine if no production data exists yet).
- None of the other scenario/content files reference `role_5` (checked via the diff scope); the change is self-consistent.

---

## Commit 2 — `27a73a2`
**Commit:** `27a73a2eb7f5fab54a12cb0a195b10b8a74a15e9`
**Message:** `Backend: fix simulation/API bugs found in QA (BUG-3,5,7,10,11,13)` (body lists each fix and notes regression tests were added)
**Date:** 2026-09-17 10:39:05 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
Six backend fixes: richer investigation-completion events, typed error events on interrupted SSE streams, a new `GET /sessions` endpoint, automatic session completion at the simulation time limit (with idempotent `complete()`), explanatory rejection reasons + eligible-work suggestions for failed investigation requests, and non-blocking confidence warnings on assessments. Each fix ships with an API regression test.

### Changes

#### Change 1 — `INVESTIGATION_COMPLETED` payload enrichment (BUG-3)
- **What/where:** `backend/app/services/simulation.py`, in the code that emits the completion event: the payload now includes `"label": run.label` and `"request": run.request` alongside the existing `investigation_id`, `started_event_id`, `started_at`, `due_at`.
- **Why:** The frontend (fixed in `f2210e4`/`0758617`) needs the human-readable investigation label and original request text to render the completion card; previously only the raw id was available.
- **Behavior:** Event consumers now see the label/request without needing to join back to the investigation definition.

#### Change 2 — Stream interruption surfaced as typed error event (BUG-5)
- **What/where:** `backend/app/api/routes.py`, `ask_role_stream`. The chunk-emission loop (`for chunk in markdown_chunks(response.message): yield stream_event("delta", ...)`) is now wrapped in `try/except Exception`; on failure it yields `stream_event("error", detail=f"The reply was interrupted: {exc}", status=502)` and returns, instead of letting the SSE stream end silently mid-reply.
- **Why:** Previously a failure while streaming a validated reply left the client hanging with a partial answer and no terminal event.
- **Behavior:** Clients now always receive a terminal event (`complete` or `error`).
- **Note:** Broad `except Exception` with a `noqa: BLE001` comment — deliberate, since the SSE contract requires a typed termination. It does swallow the original exception without logging, which could hide bugs server-side.

#### Change 3 — New `GET /sessions` listing endpoint (BUG-7)
- **What/where:**
  - `backend/app/api/routes.py`: new route `@router.get("/sessions", response_model=list[SessionResponse])` calling `service.list_sessions`.
  - `backend/app/services/simulation.py`: `list_sessions()` delegating to the repository.
  - `backend/app/repositories/sessions.py`: new `list_all()` doing `select(SessionRecord).order_by(SessionRecord.created_at.desc())`.
- **Why:** There was no way to enumerate sessions (QA needed it; the frontend's reload-restore path in `f2210e4` uses `GET /sessions/{id}`, but the listing supports future session-picker UI).
- **Behavior/API change:** New public endpoint returning all sessions, newest first.

#### Change 4 — Auto-complete at time limit; idempotent `complete()`; reject advancing a closed session (BUG-10)
- **What/where:** `backend/app/services/simulation.py`:
  - In `advance_time`: after appending the `TIME_ADVANCED` event, if `new_time >= scenario.scenario.duration_minutes`, the session status flips to `COMPLETED` and a `SESSION_COMPLETED` event with `payload={"reason": "time_limit"}` is appended before the commit.
  - `complete()` no longer goes through `_running_session()`; it now returns the session unchanged if already `COMPLETED` (idempotent), raises `InvalidOperationError("session must be running")` for any other non-running status, otherwise completes as before.
- **Why:** Previously a session that reached the time limit stayed `RUNNING` forever unless the user clicked End; and double-completion (e.g., UI race between auto-complete and manual End) errored.
- **Behavior:** Reaching the limit closes the exercise and immediately unlocks evaluation; advancing a completed session returns 409 (verified by the test).
- **Interaction with commit 5:** at this point `advance_time` still *raised* when the requested advance would overshoot the duration, so the final `+15` near the limit failed — fixed later in `0758617`.

#### Change 5 — Explanatory investigation rejections + eligible suggestions (BUG-11)
- **What/where:**
  - `backend/app/services/simulation.py`: when the LLM interpretation doesn't match an investigation, the generic reason string is replaced by a call to a new private method `_no_investigation_reason(session, scenario, performer_role, eligible)`, and the returned `InvestigationRequestResult` now carries `suggestions=[{"id": item.id, "label": item.label} for item in eligible]`.
  - New `_no_investigation_reason` (~65 lines) determines *why* nothing matched, in priority order:
    1. Performer role can't perform any investigation at all → "…cannot perform any investigation. Assign the request to a role that can."
    2. Some work is eligible but the text didn't match → "Try describing the evidence question more directly."
    3. Otherwise it inspects events for `INVESTIGATION_STARTED`, the role's known evidence ids, prerequisites (`all_evidence` / `any_evidence`), repeatability, and remaining time, returning either a "not enough exercise time left" message, a "more evidence is needed first (missing E…, O…)" message, or "All investigations for this role are already completed."
  - `backend/app/domain/simulation/models.py` and `backend/app/schemas/api.py`: `suggestions: list[dict[str, str]] = []` added to `InvestigationRequestResult` and `InvestigationRequestResponse`.
- **Why:** QA found rejections were opaque ("did not match") with no guidance; this turns a dead-end into coaching feedback and feeds the frontend suggestion chips (see `f2210e4`).
- **Behavior:** Rejected investigation requests now return a specific reason plus a list of currently-eligible investigations.

#### Change 6 — Confidence warnings on assessments (BUG-13)
- **What/where:**
  - `backend/app/services/simulation.py`: new `assessment_warnings(session_id, actor_role, recorded)` — for each recorded assessment snapshot with `confidence == CONFIRMED`, checks whether any of its `basis_evidence_ids` intersects the role's observations/findings with `reliability == Reliability.CONFIRMED`; if not, appends a warning string. A comment states the intent: "The mistake stays the lesson; the trainee just learns about it now instead of at scoring time."
  - `backend/app/api/routes.py`, `record_assessment`: calls `service.assessment_warnings(...)` and includes the result in `AssessmentSubmissionResponse`.
  - `backend/app/schemas/api.py`: `warnings: list[str] = []` added to `AssessmentSubmissionResponse`.
  - Import of `Reliability` added to the service.
- **Behavior:** Over-confident assessments are still recorded (non-blocking) but the response now warns the trainee.

#### Change 7 — Regression tests
- **What/where:** `backend/tests/test_api.py` (+105 lines) adds:
  - `test_sessions_can_be_listed` — empty list, then created session appears with status `created`.
  - `test_session_completes_automatically_at_the_time_limit` — advancing 180 min completes the session, evaluation unlocks, repeat `complete()` returns 200, advancing a completed session returns 409.
  - `test_investigation_rejection_explains_performer_mismatch` — asking the CEO to do SOC work yields "cannot perform any investigation" and empty suggestions.
  - `test_investigation_rejection_lists_eligible_suggestions` — gibberish request from `soc` returns suggestions including `I001`, `I002`.
  - `test_confirmed_assessment_without_confirming_evidence_warns` — a "confirmed" assessment based on O004 records but produces exactly one warning.

### Files Changed
- `backend/app/api/routes.py` — new `GET /sessions`; try/except around stream chunk emission; assessment warnings wired into the response.
- `backend/app/domain/simulation/models.py` — `suggestions` field on `InvestigationRequestResult`.
- `backend/app/repositories/sessions.py` — `list_all()`.
- `backend/app/schemas/api.py` — `suggestions` on `InvestigationRequestResponse`; `warnings` on `AssessmentSubmissionResponse`.
- `backend/app/services/simulation.py` — auto-complete, idempotent complete, `_no_investigation_reason`, `assessment_warnings`, `list_sessions`, enriched completion payload.
- `backend/tests/test_api.py` — five new regression tests.

### Technical Notes
- **API surface:** two additive, backward-compatible schema changes (defaulted fields) and one new endpoint.
- **State machine:** session lifecycle now has an automatic `RUNNING → COMPLETED` transition inside `advance_time`; `complete()` became a proper idempotent operation. This is the cleanest way to support both auto- and manual close racing each other.
- **Data flow:** the `_no_investigation_reason` method reads the full event log (`self.repo.events(session.id)`) plus role knowledge on every rejection — fine at this scale, but it's an O(events) scan per rejected request.
- **Error handling:** the SSE error-event pattern makes the stream protocol total (always terminated), matching what the frontend now relies on.

### Potential Issues / Things to Review
- The `except Exception` in `ask_role_stream` does not log the original exception anywhere — server-side diagnosis of stream interruptions will rely only on the client-visible message.
- `GET /sessions` has no pagination or auth scoping; it returns every session record. Acceptable for a single-trainer app, but it will grow unbounded.
- In `_no_investigation_reason`, the "not enough exercise time" branch returns on the *first* time-blocked investigation even if a later, shorter one might fit — the loop `return`s rather than continuing to check other candidates. Minor logic imprecision (a shorter investigation could still be available).
- `suggestions: list[dict[str, str]]` is untyped dict rather than a named schema — loose typing in both domain model and API schema.
- The auto-complete check uses `>=` against `duration_minutes`, while the (then-current) overshoot guard used `>`; combined they mean exactly-at-limit advances complete the session — consistent, but the interaction was only fully exercised after `0758617`'s clamping change.

---

## Commit 3 — `f2210e4`
**Commit:** `f2210e42ddfa9ad6a28654bfdeab527d5ff43f8b`
**Message:** `Frontend: fix QA bugs and add gameplay improvements (BUG-2,4,5,6,8,9,10,11,12,13, IMP-E)` (body lists ten UI fixes)
**Date:** 2026-09-17 10:39:05 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
The frontend counterpart to the backend batch: fixes the streaming placeholder leak, unread badges, interrupted-stream handling, session restore after reload, evidence sharing UI, time-limit UX, suggestion chips, live event polling, assessment warning notices, and adds the per-rule evaluation debrief on the completion screen.

### Changes

#### Change 1 — Streaming placeholder guard (BUG-2)
- **What/where:** `frontend/app/session/Conversation.tsx`: the "typing" placeholder render changed from `{streamingRole && (...)}` to `{streamingRole !== "" && streamingRole === roleId && (...)}`.
- **Why/behavior:** The placeholder was being rendered for the wrong role in some case (an empty-string vs. falsy edge and role matching); now it only appears in the conversation of the role actually streaming.

#### Change 2 — Accurate unread badges on load (BUG-4)
- **What/where:** `frontend/app/session/useSession.ts`, reducer `loaded` case: instead of only setting `lastSeen` on the *first* load (`state.session === null`), every load now does `lastSeen[activeThread] = Math.max(existing ?? 0, maxSequence)`.
- **Why/behavior:** Previously, refreshing while on a thread left stale `lastSeen` values so unread badges showed phantom counts; now the active thread is always marked seen up to the newest event, and `Math.max` prevents regressing a newer seen-position.

#### Change 3 — Treat unfinished reply stream as error (BUG-5)
- **What/where:** `frontend/app/session/useSession.ts`, `sendMessage`: tracks a `completed` flag set when the `complete` stream event arrives; after the `for await` loop, if `!completed`, throws `"The reply was interrupted before it finished. Please retry."`.
- **Why/behavior:** Pairs with backend BUG-5: if the SSE stream ends without a terminal event (network drop), the UI now shows an error/retry instead of silently leaving a partial reply. Note the backend's new `error` event was already handled (`throw new Error(item.detail)`); this closes the *no-terminal-event-at-all* hole.

#### Change 4 — Restore running session after reload (BUG-6)
- **What/where:** `frontend/app/page.tsx`:
  - New constant `ACTIVE_SESSION_KEY = "incident-room-active-session"` in `localStorage`.
  - On start: `localStorage.setItem(ACTIVE_SESSION_KEY, started.id)` after `/start` succeeds.
  - On mount (inside the `/scenarios` load): reads the saved id, `GET /sessions/{savedId}`; if `status === "running"` and the scenario still exists, restores `scenarioId`/`variantId`/`sessionId` (dropping straight back into the room); otherwise removes the key. Fetch failure also removes the key.
  - On completion (`onComplete`): removes the key.
- **Behavior:** Reloading the page mid-exercise rejoins the running session instead of dumping the trainee back at the launcher.

#### Change 5 — Share-with control on evidence cards (BUG-8/9)
- **What/where:**
  - `frontend/app/session/ContextRail.tsx`: evidence cards now compute `holders` and `receivers` (roles not holding the item) and, when both are non-empty, render a "Share with" `<select>` listing receiver roles. On change it calls `onShare(holders[0], to, item.id)` and resets the select. New props: `busy` (disables the select) and `onShare`.
  - `frontend/app/session/SessionView.tsx`: wires `busy={state.busy}` and `onShare={controller.shareEvidence}` into `ContextRail`.
  - `frontend/app/session/useSession.ts`: new `shareEvidence(fromRole, toRole, evidenceId)` callback POSTing to `/sessions/{id}/actions/share-evidence` and refreshing.
  - `frontend/app/session/Conversation.tsx`: `EVIDENCE_SHARED` events now render as a system message ("Evidence shared with {role}") in the target role's DM, and are included in the DM filter predicate.
  - `frontend/app/styles.css`: `.evidence-share` styling was already present; new `.room-notice`, `.composer-suggestions`, `.room-time-expired`, and `.debrief-*` styles added in this commit.
- **Behavior:** Trainees can share discovered evidence between roles directly from the context rail — previously sharing existed in the backend but had no UI (QA BUG-8/9).
- **Note:** `onShare(holders[0], to, ...)` always shares *from the first holder*, not from the currently-viewed role — a deliberate simplification, but it means the acting role isn't necessarily the sharer.

#### Change 6 — Time-limit UX (BUG-10)
- **What/where:** `frontend/app/session/TopBar.tsx`: `timeExpired = session.simulation_time >= scenario.duration_minutes`; both `+5`/`+15` buttons get `disabled={busy || timeExpired}` and an amber "Time limit reached — End exercise to see your result" span appears.
- **Behavior:** Matches the backend auto-complete state; guides the trainee to end the exercise. (At this commit the backend could still error on an overshooting advance — resolved by `0758617`.)

#### Change 7 — Suggestion chips on rejected work requests (BUG-11 / IMP-1)
- **What/where:**
  - `frontend/app/session/useSession.ts`: new state `suggestions` + `suggestions` action; `requestWork` clears suggestions, and on `!accepted` dispatches the returned `result.suggestions ?? []` before throwing the reason as an error.
  - `frontend/app/session/Composer.tsx`: new `suggestions` prop; in `investigate` mode renders an "Available work:" row of dashed chip buttons that populate the composer text (`setText(item.label)`).
  - `frontend/app/session/SessionView.tsx`: passes `suggestions={state.suggestions}` to the Composer.
  - `frontend/app/styles.css`: `.composer-suggestions` styles.
- **Behavior:** When an investigation request is rejected, the trainee sees clickable labels of what the role *can* actually do.

#### Change 8 — Live event polling (BUG-12)
- **What/where:** `frontend/app/session/useSession.ts`: new `useEffect` interval (5 s) that, when not busy/streaming (`busyRef`, set from `state.busy || state.streamingRole !== ""`) and `!document.hidden`, fetches `/sessions/{id}/events` and compares the last `sequence` against `lastSequenceRef`; if changed, calls full `refresh()`. Errors are swallowed.
- **Why:** Backend-produced events (investigation completions landing asynchronously, another tab, instructor actions) were invisible until manual reload.
- **Behavior:** The room syncs within ~5 s. Cost: polls the *entire* event list every 5 s (no `since` parameter), then re-fetches everything on change — fine at current scale, O(events) per poll.

#### Change 9 — Assessment confidence notice (BUG-13)
- **What/where:** `frontend/app/session/useSession.ts`: new `notice` state + action; `recordAssessment` dispatches a notice joining `result.warnings`. Reducer clears the notice when a busy operation starts and on error. `frontend/app/session/SessionView.tsx` renders `state.notice` as an amber `room-notice` banner (only when there's no error).
- **Behavior:** The backend's confirmed-without-confirming-evidence warnings now appear as a dismissible-by-next-action banner.

#### Change 10 — Per-rule evaluation debrief (IMP-E)
- **What/where:**
  - `frontend/app/session/types.ts`: new `EvaluationRule` type (`rule_id`, `description`, `possible_points`, `awarded_points`, `expected_action`, `expected_by_minute`, `actual_action`, `actual_minute`); `Evaluation` and `Completion` gain `rules`.
  - `frontend/app/session/SessionView.tsx`: `rules: evaluation.rules ?? []` added to the completion object.
  - `frontend/app/page.tsx`: the completion screen renders a `<ul className="debrief-list">` — one item per rule, classed `debrief-hit` (full points, green), `debrief-partial` (amber), or `debrief-miss` (red), showing awarded/possible points, description, expected action (+ deadline minute), and actual action (+ minute) or "No matching action recorded."
  - `frontend/app/styles.css`: `.debrief-list`, `.debrief-hit/partial/miss` styles.
- **Behavior:** Trainees see exactly which rubric rules they hit/missed after the exercise — previously only a total score.
- **Note:** `rules` is typed as required on `Evaluation` but populated with `?? []`, so an older backend without `rules` degrades gracefully.

### Files Changed
- `frontend/app/page.tsx` — localStorage session restore; debrief list rendering.
- `frontend/app/session/Composer.tsx` — suggestion chips in investigate mode.
- `frontend/app/session/ContextRail.tsx` — Share-with select on evidence cards.
- `frontend/app/session/Conversation.tsx` — `EVIDENCE_SHARED` rendering/filter; streaming placeholder guard.
- `frontend/app/session/SessionView.tsx` — notice banner; wire `suggestions`, `busy`, `onShare`; pass `rules` into completion.
- `frontend/app/session/TopBar.tsx` — disable advance at time limit + banner.
- `frontend/app/session/types.ts` — `EvaluationRule`, `rules` on `Evaluation`/`Completion`.
- `frontend/app/session/useSession.ts` — `notice`/`suggestions` state, stream-completion check, polling effect, `shareEvidence`, `lastSeen` fix.
- `frontend/app/styles.css` — styles for notices, chips, debrief, time-expired.

### Technical Notes
- **State management:** the reducer gained two orthogonal transient channels — `error` (blocking) and `notice` (advisory) — with clear precedence rules (busy clears notice; error clears notice).
- **Data flow:** polling introduces a background writer into an otherwise action-driven refresh model; guarded by `busyRef` (a ref mirroring busy state, avoiding stale-closure issues) and `document.hidden`.
- **No frontend tests** accompany any of this — the repo has no frontend test infrastructure, so all ten changes are verified only by manual playthrough (which did happen: BUG-14..17 were found this way).

### Potential Issues / Things to Review
- The 5 s poll refetches the full event array and, on any change, triggers a full multi-endpoint `refresh()`; no `since`/cursor parameter exists. Wasteful but correct at current scale.
- `shareEvidence` uses `holders[0]` as the sender regardless of which role the trainee is acting as — semantically odd if multiple holders exist.
- Mutating `event.target.value = ""` after firing `onShare` on a `defaultValue`-controlled select is an imperative reset; works, but is an unusual React pattern.
- Session restore in `page.tsx` runs inside the scenarios `.then()`; if `/sessions/{savedId}` is slow, the launcher briefly renders before jumping into the room (minor UX flicker).
- The poll's `.catch(() => undefined)` hides persistent backend failures silently.

---

## Commit 4 — `fde3605`
**Commit:** `fde3605557326daab2cfcbb1c8ddb6e32abfe5d0`
**Message:** `Add QA bug report, gameplay review, and improvement notes`
**Date:** 2026-09-17 10:39:05 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
Documentation-only commit adding three QA artifacts: `BUG_REPORT.md` (253 lines, BUG-1..13), `GAMEPLAY_REVIEW.md` (127 lines, IMP-A..G from two full playthroughs, one scoring 100/100 and one 0/100), and `IMPROVEMENTS.md` (107 lines, IMP-1..8 roadmap).

### Changes

#### Change 1 — QA documentation added
- **What/where:** three new Markdown files at the repo root; no code touched.
- **Why:** These are the source documents the bug IDs referenced in `60c35fe`, `27a73a2`, and `f2210e4` refer to. They were committed *after* the fixes in branch order (all four share the same timestamp 10:39:05 — likely a rebased/split commit series), so the branch history reads: fixes first, then the reports they came from.

### Files Changed
- `BUG_REPORT.md` — new, 253 lines.
- `GAMEPLAY_REVIEW.md` — new, 127 lines.
- `IMPROVEMENTS.md` — new, 107 lines.

### Technical Notes
- No behavioral impact. Note that two of these three files are deleted again two commits later (`a4248cf`), so on the branch tip only `IMPROVEMENTS.md` survives.

### Potential Issues / Things to Review
- Committing detailed bug reports and then deleting them (`a4248cf`) keeps them in history but leaves no pointer from the code to the QA process; the fix commits reference BUG-n IDs that no longer resolve to any file at HEAD. Minor traceability concern, not a defect.

---

## Commit 5 — `0758617`
**Commit:** `0758617ed03c2c7ec8c76568056f25008b2fbed0`
**Message:** `Fix issues found in second playthrough (BUG-14..17)` (body lists the four fixes and a regression test)
**Date:** 2026-09-17 11:10:47 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
Follow-up fixes discovered by playing the game again after the first fix batch: the last `+15` near the time limit no longer errors (it clamps and completes), investigation cards appear in the performer's DM thread, investigation record cards show the matched label instead of raw request text, and the evaluation debrief shows human-readable action labels instead of raw event-type enums.

### Changes

#### Change 1 — Clamp advance-time instead of erroring (BUG-14)
- **What/where:** `backend/app/services/simulation.py`, `advance_time`: the guard `if new_time > duration: raise InvalidOperationError(...)` was replaced with `new_time = min(old_time + minutes, duration)`. The `TIME_ADVANCED` payload's `minutes` field now reports the *effective* advance (`new_time - old_time`) rather than the requested amount.
- **Why:** With BUG-10's auto-complete in place, pressing `+15` at T+170 of a 180-min scenario previously 409'd; now it advances to exactly 180 and the auto-complete logic from `27a73a2` closes the session cleanly.
- **Behavior:** Overshooting advances succeed with clamping; the audit event records honest elapsed minutes.
- **Test:** `test_advance_time_clamps_to_the_scenario_duration` — advance 170, then +15 → 200, `simulation_time == 180`, `status == "completed"`.

#### Change 2 — Investigation cards in the performer's DM (BUG-15)
- **What/where:** `frontend/app/session/Conversation.tsx`, DM filter predicate: `INVESTIGATION_STARTED`/`INVESTIGATION_COMPLETED` events are now included when `event.actor_role === roleId || event.target_role === roleId`.
- **Why/behavior:** Previously these cards appeared only on the bridge feed; now both requester-side context (target) and performer-side (actor) DMs show the work happening — matching how a real incident channel would look.

#### Change 3 — Matched label on investigation record cards (BUG-16)
- **What/where:** `frontend/app/session/Conversation.tsx`, `StructuredEvent`: body now prefers `payload.label`, falling back to `request`, then `investigation_id`; the raw request text is shown as secondary detail appended to the `actor → target` sub-line only when it differs from the label.
- **Why:** Depends directly on `label`/`request` being added to the completion payload in `27a73a2` (BUG-3) — this is the consumer that motivated it. Previously the card showed the trainee's free-text request verbatim, which read poorly.

#### Change 4 — Human-readable action labels in the debrief (BUG-17)
- **What/where:** `backend/app/domain/evaluation/engine.py`: new class-level `ACTION_LABELS = {QUESTION_ASKED: "Contacted the role", EVIDENCE_SHARED: "Shared the evidence"}`; the rule's `actual_action` now maps through `ACTION_LABELS.get(event_type, event_type.value)` for non-`DECISION_MADE` events.
- **Why/behavior:** The debrief (rendered by `f2210e4`) previously displayed raw enum values like `question_asked`; now it reads "Contacted the role". `DECISION_MADE` keeps its existing special-case (the decision string).

### Files Changed
- `backend/app/domain/evaluation/engine.py` — `ACTION_LABELS` map + lookup in `actual_action`.
- `backend/app/services/simulation.py` — clamping + effective-minutes payload.
- `backend/tests/test_api.py` — clamping regression test.
- `frontend/app/session/Conversation.tsx` — DM filter for investigation events; label-first card rendering.

### Technical Notes
- This commit *corrects and completes* work from `27a73a2` (time-limit behavior), `f2210e4` (debrief display, investigation cards), and consumes the BUG-3 payload fields.
- The `ACTION_LABELS` map covers only the two event types currently used by rubric rules; unknown types fall back to the raw enum value, so future rule types will regress to raw labels until added.
- Operator-precedence note: the new filter predicate mixes `||` and `&&` without parentheses around the investigation clause (`A || B || C && D || E`). It evaluates as intended (`&&` binds tighter), but is fragile to future edits — worth parenthesizing.

### Potential Issues / Things to Review
- Clamping means `advance_time` can no longer signal a user mistake; any caller relying on the old 409 for overshoot (none found in this repo) would change behavior. The audit `minutes` field semantics changed from "requested" to "elapsed" — consumers of that payload must know.
- No test asserts the *payload* `minutes` value after clamping, only the resulting `simulation_time`/`status`.

---

## Commit 6 — `a4248cf`
**Commit:** `a4248cf474165ff6555bbe5a28eae07cba25a03e`
**Message:** `Remove resolved QA reports; mark implemented items in IMPROVEMENTS.md` (body: BUG-1..13 and IMP-A..G fixed and verified; IMPROVEMENTS.md kept as roadmap with status header)
**Date:** 2026-09-17 11:12:54 +0200
**Author:** Rok Plesko <rp9376@student.uni-lj.si>

### Summary
Housekeeping: deletes the two resolved QA documents and prepends a status header to `IMPROVEMENTS.md` recording what was implemented on this branch and what remains open.

### Changes

#### Change 1 — Delete resolved QA documents
- **What/where:** `BUG_REPORT.md` (−253) and `GAMEPLAY_REVIEW.md` (−127) deleted.
- **Why:** Per the commit message, all BUG-1..13 and IMP-A..G they tracked are fixed and verified on this branch.
- **Note:** The message says "BUG-1..13", but the branch actually also fixed BUG-14..17 (`0758617`) — the status header in `IMPROVEMENTS.md` does say "BUG-1…BUG-17", so the header is more accurate than the commit body.

#### Change 2 — Status header in `IMPROVEMENTS.md`
- **What/where:** +5 lines at the top of `IMPROVEMENTS.md`:
  - All BUG-1…BUG-17 fixed; bug-report/review docs removed once resolved.
  - Implemented: IMP-1 (suggestion chips), IMP-2 (Share-with control — hover "not yet shared with" still open), IMP-4 (per-rule debrief), IMP-5 partially (stream errors surface; optimistic question echo and typing indicator still open), and review items IMP-A/B/C/D/E/F.
  - Still open: IMP-3 (timeline strip/replay), IMP-6 (decision confirm/undo), IMP-7 (editor lint for placeholder/dangling content), IMP-8 (engineering hygiene), IMP-G (coordinator onboarding panel).
- **Behavior:** None — documentation. It does, however, explicitly acknowledge that IMP-7 (editor lint for placeholder content like the `role_5` entry) is *not* done even though `60c35fe` removed one instance — consistent, not contradictory.

### Files Changed
- `BUG_REPORT.md` — deleted.
- `GAMEPLAY_REVIEW.md` — deleted.
- `IMPROVEMENTS.md` — status header added.

### Technical Notes
- Net effect vs. `fde3605`: across the branch, only `IMPROVEMENTS.md` (with header) is added at HEAD; the other two documents exist only in intermediate history.

### Potential Issues / Things to Review
- Fix commits reference BUG-n identifiers that no longer resolve at HEAD (documents deleted). Consider keeping the reports or linking to the (closed) issues if traceability matters.

---

## Cross-Commit Analysis

**One coherent QA cycle, split by layer.** All six commits serve a single effort: a QA pass, its fixes, a second playthrough, and cleanup. The split is by concern — data (`60c35fe`), backend (`27a73a2`), frontend (`f2210e4`), docs (`fde3605`) — plus a follow-up correction batch (`0758617`) and housekeeping (`a4248cf`). The first four share an identical timestamp (10:39:05), strongly suggesting they were authored/committer-dated together (e.g., via a rebase or scripted split) even though the logical order is: QA docs → fixes.

**Later commits correct or complete earlier ones:**
- `0758617` directly modifies code introduced in `27a73a2`: the overshoot `raise` in `advance_time` (pre-existing, but the auto-complete logic from `27a73a2` made the final `+15` a dead end) is replaced with clamping, and the `TIME_ADVANCED` payload's `minutes` semantics changed from requested to elapsed.
- `0758617` consumes the `label`/`request` payload fields added in `27a73a2` (BUG-3) — the frontend rendering fix (BUG-16) could not have worked without that backend change, and interestingly `f2210e4` (which sits *between* them) shipped the card renderer before the payload carried a label, so at `f2210e4` the card still fell back to raw request text.
- `0758617`'s `ACTION_LABELS` (BUG-17) fixes the display quality of the debrief UI that `f2210e4` introduced (IMP-E).
- `0758617` extends `f2210e4`'s `Conversation.tsx` DM filter (adding investigation events after `f2210e4` added `EVIDENCE_SHARED`).
- `a4248cf` deletes two of the three files added in `fde3605`.

**Introduced-then-changed-again code:** `Conversation.tsx` (touched in `f2210e4`, then again in `0758617`), `services/simulation.py` `advance_time` (touched in `27a73a2`, then again in `0758617`), `backend/tests/test_api.py` (grown in both backend commits), and the QA docs (added then deleted).

**Duplicated/overlapping work:** none problematic. The BUG-10 (time limit) fix is intentionally split backend/frontend and then refined once more — the three pieces compose correctly at HEAD. The frontend BUG-5 handling (`completed` flag) and backend BUG-5 handling (typed error event) are complementary, not duplicated: backend covers "exception while streaming", frontend covers "stream vanished without terminal event".

**Would make more sense considered together / as squashed:** if this branch is merged as a PR, `fde3605` + `a4248cf` largely cancel out (net: `IMPROVEMENTS.md` with a status header); and `0758617` is a direct refinement of `27a73a2`+`f2210e4`. A squash of `fde3605`+`a4248cf`, or of the two backend commits, would produce a cleaner history — but that is a merge-strategy choice, not a defect.

**Residual risks across the set (supported by the diffs):**
1. No logging of the swallowed exception in the SSE stream handler (`27a73a2`).
2. Full-event-list polling every 5 s with no cursor (`f2210e4`) — scales poorly but correct.
3. `shareEvidence` always sends from `holders[0]` (`f2210e4`).
4. `_no_investigation_reason` returns "not enough time" on the first time-blocked candidate without checking shorter ones (`27a73a2`).
5. No automated tests for any frontend change; QA was manual, and indeed the second manual pass found four more bugs.
6. `ACTION_LABELS` will silently fall back to raw enums for future event types (`0758617`).
7. Bug-ID traceability is lost at HEAD because the reports were deleted (`a4248cf`).
