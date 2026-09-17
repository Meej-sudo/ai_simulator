# Improvement Proposals — Incident Room

**Date:** 2026-09-17
**Companion to:** `BUG_REPORT.md` (fixes first; these are UX/product/engineering improvements observed during the same QA pass).
**Update (full playthroughs):** see `GAMEPLAY_REVIEW.md` for IMP-A…IMP-G from two complete runs (Alpha 100/100, Bravo 0/100). IMP-A (visible sharing) and IMP-D (end-of-time state) are the highest-leverage additions; IMP-1 below is superseded by IMP-B in the review.

**Status after the fix branch (`fix/qa-bugs-and-improvements`, 2026-09-17):**
All BUG-1…BUG-17 from the QA passes are fixed and the bug-report/review documents were removed once resolved.
Implemented from this list: **IMP-1** (suggestion chips on rejected work requests), **IMP-2** (Share-with control on evidence cards; hover "not yet shared with" still open), **IMP-4** (per-rule debrief on the close screen), **IMP-5** partially (stream errors now surface; optimistic question echo and a typing indicator are still open), and review items **IMP-A/B/C/D/E/F**.
Still open: **IMP-3** (timeline strip / replay), **IMP-6** (decision confirm/undo), **IMP-7** (editor lint for placeholder/dangling content), **IMP-8** (engineering hygiene), **IMP-G** (coordinator onboarding panel).

---

## IMP-1 — Surface *available* investigations to the trainee

**Observation**
The first investigation request ("Determine scope of encryption… whether svc_backup was used for lateral movement") was rejected with *"The request did not match a currently available investigation."* The message is honest but a dead end — the trainee has no idea what *is* available, and matching depends on phrasing that happens to hit `match_hints` (login source / source ip…).

**Proposal**
- Return the list of currently eligible investigations (id + label + request_description) in the rejection payload (`simulation.py` already computes `eligible` in `request_investigation`), and render them as clickable suggestions in the error banner / composer.
- Or show a persistent "Suggested work" section in the ContextRail derived from `_eligible_investigations()`.
- Clicking a suggestion prefills the composer with `request_description`.

**Where:** `backend/app/services/simulation.py` (`request_investigation` result), `backend/app/schemas/api.py`, `frontend/app/session/Composer.tsx` + `useSession.ts`.

---

## IMP-2 — Show evidence holders per role vs. exercise-wide more clearly

**Observation**
The Discovered-evidence panel says "Roles only use evidence they hold", and the chip shows "held by SOC Analyst". When multiple roles hold the same item, `useSession.discoveredEvidence` appends duplicate holder entries (it merges by pushing `roleId` per role — fine), but there's no way to see *who doesn't* hold it, which is exactly the coordination challenge the exercise is about.

**Proposal**
- Show holders as avatars and, on hover, "not yet shared with: CISO, DPO, CEO".
- Add a "Share with…" affordance (a new backend action that grants a role an evidence item via a message), which currently doesn't exist — roles can't share findings with each other, making cross-role coordination shallow.

**Where:** `frontend/app/session/ContextRail.tsx`, new backend action `POST /sessions/{id}/actions/share_evidence` in `routes.py` + `simulation.py`.

---

## IMP-3 — Timeline scrubber / clock realism

**Observation**
Time only advances via +5/+15 buttons; `TIMELINE_EVENT_TRIGGERED` events at T+5/T+10 retroactively appear when you jump +15, all stamped at their scheduled minute. That's fine, but the trainee can't see *what's coming* or replay *when* they learned things.

**Proposal**
- A compact timeline strip under the TopBar showing scheduled events discovered so far (dots at T+5, T+10…) with tooltips.
- Post-exercise replay mode: step through the event log by sequence to review how knowledge spread — strong fit for a training product and the existing audit-event architecture.

**Where:** new component in `frontend/app/session/`, data already available from `/events`.

---

## IMP-4 — Evaluation transparency

**Observation**
End screen shows only "Final score 60/100" + audit reference. The scoring rubric exists in the scenario (`Scoring 4` in the editor), but the trainee gets no breakdown — a missed learning opportunity for a training tool.

**Proposal**
- Render the per-criterion breakdown from `/evaluation` (which hypotheses confirmed, decisions timed right, notification obligations met).
- Add a "Review exercise" link that opens the event log grouped by category.

**Where:** `frontend/app/page.tsx` completion notice + a new `ReviewView`; `backend/app/domain/evaluation/engine.py` already produces the data.

---

## IMP-5 — Streaming UX: optimistic user message + typing indicator

**Observation**
While a DM reply streams, the user's own question only appears after the whole round-trip (it's an event from `refresh()`), and the placeholder bubble is empty with no "typing" affordance. With a 27B local model the wait is 10–40 s — long enough to feel broken (it did prompt a bug report twice).

**Proposal**
- Optimistically render the trainee's question immediately on submit.
- Show an animated "SOC Analyst is analyzing…" indicator (the `start` stream event already arrives instantly) instead of an empty bubble.
- Keep the existing chunked replay of the validated answer.

**Where:** `frontend/app/session/useSession.ts` (optimistic entry), `Conversation.tsx` (indicator when `streamingRole` set but `streamingText` empty).

---

## IMP-6 — Guard rails around acting "as" roles

**Observation**
The trainee can log assessments/decisions attributed to *any* role (CEO, DPO…) with no confirmation, even ones that make no narrative sense (e.g., SOC Analyst making a containment decision at T+0 with one observation). The rail note says "Actions are still attributed to in-game roles", so this is by design — but misclicks silently corrupt the scored audit trail.

**Proposal**
- Confirm dialog (or undo action) when recording a decision, since decisions are scored.
- Optionally soft-warn when the acting role's responsibilities don't mention the decision category.

**Where:** `frontend/app/session/Composer.tsx`; optional backend soft-check in `simulation.py` (log a warning flag on the event, don't block).

---

## IMP-7 — Scenario editor: validation & reference integrity

**Observation**
The editor saves "after the complete scenario passes validation", yet `role_5` (BUG-1) shipped with placeholder text and zero connections to evidence/investigations/timeline. Validation apparently checks structure, not dangling/placeholder content.

**Proposal**
- Add lint rules: warn on roles/evidence/investigations never referenced by any timeline event, variant, or scoring rule; flag placeholder strings ("New role", "Describe this…").
- Show a references graph per item ("used by: E002, I003, variant track_alpha").

**Where:** `backend/app/domain/scenarios/compiler.py` (validation), `frontend/app/ScenarioEditor.tsx` (warnings panel).

---

## IMP-8 — Engineering hygiene

- **Event-payload typing:** audit payloads are free-form dicts; the frontend re-narrows with `asString`/`asStrings` everywhere. A shared schema (OpenAPI-generated types or a small zod/pydantic-mirror) would have caught BUG-3 (missing `label` on `INVESTIGATION_COMPLETED`) at build time.
- **Polling cost:** every action triggers ~10 requests (session, roles, events, investigations, assessments + one knowledge request *per role*). Batch into a single `/sessions/{id}/snapshot` endpoint, or add `?since=sequence` to `/events` and update incrementally.
- **`/settings/llm/models` polled every 10 s** by the launch page even when the config panel is untouched — use ETag/`If-None-Match` or only poll while the panel is focused.
- **Test coverage:** add frontend tests for the reducer (`lastSeen` semantics, BUG-4) and Conversation rendering with `streamingRole=""` (BUG-2); backend test asserting `INVESTIGATION_COMPLETED` payload shape (BUG-3).
