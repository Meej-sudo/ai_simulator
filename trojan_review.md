# Playthrough Review: *Trojan horse spread from a fraudulent job application* (Track Alpha)

**Full playthrough done**: ~10 in-game actions over T+0 → T+75 — SOC questioning, 3 investigations (1 rejected → suggested → accepted), evidence sharing, fraud decision, two stakeholder negotiations (CEO, DPO), a confirmed assessment, and the end-of-exercise evaluation. **Final score: 140/170.**

---

## What happened (short version)

The SOC analyst gave a textbook evidence-disciplined briefing. I analyzed the attachment (RAT via macro-CV), spotted the payroll anomaly, shared it with HR, and froze the four fraudulent bank changes before the 22:00 payroll run. The HR Director's reply was genuinely moving — guilt, shaky hands, asking *me* to make the call on freezing and on what to tell the affected employees. Then the CEO surfaced demanding business-language options, the DPO demanded forensic rigor before any "breach" language, and I ran the destination → forensics chain to FD011 (full HR export confirmed exfiltrated) before declaring exfiltration confirmed. The CEO immediately fired back with a board-brief challenge. I missed the containment decision window entirely and ate a 30-point penalty.

## What's genuinely excellent

1. **The scenario design is the best of the two.** Three interlocking clocks — spreading trojan, payroll fraud with a hard 22:00 deadline, and an ambiguous data exfil — force triage instead of checklist completion. Track Bravo's "legitimate vendor transfer" counter-truth (FD012–FD015 mirror the alpha findings) is a clever discrimination test: the same initial observation (O005) means opposite things depending on which investigation chain you pursue.

2. **Stakeholder-initiated requests are a big step up.** The CEO doesn't wait to be asked — he shows up demanding "two options and a recommendation, in plain business terms," and the DPO explicitly pushes back on premature "breach" language. The **follow-up challenge (FU001)** — CEO grilling me after I marked exfiltration confirmed — triggered exactly as designed and made the final hour feel like a real executive briefing. This is the feature that makes the sim feel alive.

3. **The roles stay in-character and evidence-bounded.** The SOC listed "gaps I need closed" instead of speculating; the HR Director asked "what do we tell the employees, and when?" — the human dimension the ransomware scenario mostly lacks. HR guilt over the CV passing *her* workflow was an unexpected emotional beat.

4. **Guardrails work.** Premature "confirmed" assessment produced a warning banner ("no confirmed-reliability evidence supports that confidence level yet") without blocking me — right call. Rejected investigation requests surface a concrete "Available work" suggestion chip. Scoring feedback at the end is transparent: every rule shows expected vs. actual.

## What needs work

1. **Nothing teaches the containment decision.** I lost 30 points because no signal ever said "isolate the host / contain." The CEO event (E023) actually pressures the *opposite* way (restore services fast) — good tension, but the scenario gives zero counter-nudge. A single helpdesk-style event ("more endpoints executing the macro") or a SOC line ("recommend isolation, awaiting your decision") would make the miss *my* failure rather than a blind spot. As it stands, a trainee can finish the whole fraud+privacy arc and never learn containment was scored.

2. **Duplicate decisions are silently accepted.** I recorded the same fraud decision twice (partly my fumbling, see #3) and the audit log now shows two identical `Decision · fraud_prevention` records at T+30. No confirmation, no dedupe, no "replace previous decision?" — this pollutes the audit trail instructors grade on.

3. **Composer state leaks across threads and modes.** My draft text and selected mode persisted when switching DM → bridge → DM; in one case my message text landed in the *Request work* box because the composer had stayed in that mode after a rejected request. Combined with #2, this is how accidental duplicates happen.

4. **Timeline events are information-free.** "A scheduled incident update became available" ×7 in the bridge. It tells the trainee *something* happened but not what — you have to go hunt the evidence rail. Even "New telemetry available for review" would be better.

5. **Pacing nit:** evidence drips on a fixed schedule (O005/O006 at T+45) regardless of what you've investigated, so the outbound-transfer plot can't even be *noticed* before T+45 — yet the DPO scoring window is measured from it. Fine, but the first 45 minutes feel scripted; the scenario trusts the fraud clock too much to carry the early game.

6. **Minor:** after a backend restart the model config briefly showed "qwen3.8:27b · currently unavailable" until the 10s discovery cycle caught up — cosmetic, but it looks broken at exactly the wrong moment (starting an exercise).

## Verdict

**8.5 / 10.** The strongest content in the repo — the three-clock structure, the Alpha/Bravo evidence mirror, and the proactive stakeholder requests put it clearly above the ransomware scenario. The roleplay quality (DPO's "suspected exposure, and I will push back on stronger language" is *chef's kiss* for a privacy-training sim) does real teaching work. It loses points on game-feel: an unsignposted scored objective (containment), no protection against duplicate audit entries, and composer state leakage. Fix those three and it's a 9.5.

**Would I run a trainee through this instead of the ransomware one? Yes — it's the better teaching scenario, precisely because the DPO and CEO punish sloppy certainty.**