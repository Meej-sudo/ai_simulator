"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import ModelConfiguration from "./ModelConfiguration";
import ScenarioEditor from "./ScenarioEditor";
import { api, streamApi } from "./api";

type Variant = { id: string; name: string };
type DecisionCategory = {
  id: string;
  display_name: string;
  description: string;
  captures_confidence: boolean;
};
type Scenario = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  variants: Variant[];
  decision_categories: DecisionCategory[];
};
type Session = {
  id: string;
  scenario_id: string;
  variant_id: string;
  simulation_time: number;
  status: "created" | "running" | "completed";
};
type Role = { id: string; display_name: string; responsibilities: string[] };
type Fact = { id: string; statement: string; confidence: string };
type Knowledge = { role_id: string; simulation_time: number; facts: Fact[] };
type AuditEvent = {
  id: string;
  sequence: number;
  simulation_time: number;
  event_type: string;
  actor_role?: string;
  target_role?: string;
  payload: Record<string, unknown>;
};
type Evaluation = { total_score: number; possible_score: number };
type CompletedExercise = {
  sessionId: string;
  scenarioName: string;
  endedAtMinute: number;
  totalScore: number;
  possibleScore: number;
};

const DEFAULT_CHARACTER_INTERVAL_MS = 12;
const MIN_CHARACTER_INTERVAL_MS = 1;
const MAX_CHARACTER_INTERVAL_MS = 60;

class SmoothedTextRenderer {
  private characters: string[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private lastChunkAt: number | null = null;
  private measuredDuration = 0;
  private measuredCharacters = 0;
  private characterInterval = DEFAULT_CHARACTER_INTERVAL_MS;
  private inputComplete = false;
  private resolveComplete: (() => void) | null = null;
  private readonly completion = new Promise<void>((resolve) => {
    this.resolveComplete = resolve;
  });

  constructor(private readonly renderCharacter: (character: string) => void) {}

  enqueue(content: string) {
    const incomingCharacters = Array.from(content);
    if (incomingCharacters.length === 0) return;

    const now = performance.now();
    if (this.lastChunkAt !== null) {
      this.measuredDuration += now - this.lastChunkAt;
      this.measuredCharacters += incomingCharacters.length;
      this.characterInterval = Math.min(
        MAX_CHARACTER_INTERVAL_MS,
        Math.max(
          MIN_CHARACTER_INTERVAL_MS,
          this.measuredDuration / this.measuredCharacters,
        ),
      );
    }
    this.lastChunkAt = now;
    this.characters.push(...incomingCharacters);
    this.scheduleNextCharacter();
  }

  finish() {
    this.inputComplete = true;
    this.resolveIfComplete();
    return this.completion;
  }

  stop() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.characters = [];
    this.inputComplete = true;
    this.resolveIfComplete();
  }

  private scheduleNextCharacter() {
    if (this.timer !== null || this.characters.length === 0) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      const character = this.characters.shift();
      if (character !== undefined) this.renderCharacter(character);
      if (this.characters.length > 0) {
        this.scheduleNextCharacter();
      } else {
        this.resolveIfComplete();
      }
    }, this.characterInterval);
  }

  private resolveIfComplete() {
    if (this.inputComplete && this.characters.length === 0 && this.timer === null) {
      this.resolveComplete?.();
      this.resolveComplete = null;
    }
  }
}

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [variantId, setVariantId] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [knowledge, setKnowledge] = useState<Record<string, Fact[]>>({});
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [completedExercise, setCompletedExercise] = useState<CompletedExercise | null>(null);
  const [targetRole, setTargetRole] = useState("soc");
  const [question, setQuestion] = useState("What do we know so far?");
  const [answer, setAnswer] = useState("");
  const [answerStreaming, setAnswerStreaming] = useState(false);
  const [shareFrom, setShareFrom] = useState("soc");
  const [shareTo, setShareTo] = useState("dpo");
  const [shareFact, setShareFact] = useState("");
  const [decisionActor, setDecisionActor] = useState("ciso");
  const [decisionCategory, setDecisionCategory] = useState("containment");
  const [decisionText, setDecisionText] = useState("");
  const [decisionConfidence, setDecisionConfidence] = useState("medium");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);

  const selected = useMemo(
    () => scenarios.find((item) => item.id === scenarioId),
    [scenarios, scenarioId],
  );
  const shareableFacts = knowledge[shareFrom] ?? [];
  const selectedShareFact = shareableFacts.some((fact) => fact.id === shareFact)
    ? shareFact
    : (shareableFacts[0]?.id ?? "");
  const selectedDecisionCategory = selected?.decision_categories.find(
    (category) => category.id === decisionCategory,
  );

  useEffect(() => {
    api<Scenario[]>("/scenarios")
      .then((items) => {
        setScenarios(items);
        if (items[0]) {
          setScenarioId(items[0].id);
          setVariantId(items[0].variants[0]?.id ?? "");
          setDecisionCategory(items[0].decision_categories[0]?.id ?? "");
        }
      })
      .catch((cause) => setError(cause.message));
  }, []);

  async function refresh(id = session?.id) {
    if (!id) return;
    const [nextSession, nextRoles, nextEvents] = await Promise.all([
      api<Session>(`/sessions/${id}`),
      api<Role[]>(`/sessions/${id}/roles`),
      api<AuditEvent[]>(`/sessions/${id}/events`),
    ]);
    const knowledgePairs = await Promise.all(
      nextRoles.map(async (role) => {
        const result = await api<Knowledge>(`/sessions/${id}/roles/${role.id}/knowledge`);
        return [role.id, result.facts] as const;
      }),
    );
    setSession(nextSession);
    setRoles(nextRoles);
    setEvents(nextEvents);
    setKnowledge(Object.fromEntries(knowledgePairs));
  }

  async function run(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }

  function createSession() {
    return run(async () => {
      setCompletedExercise(null);
      const created = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ scenario_id: scenarioId, variant_id: variantId }),
      });
      const started = await api<Session>(`/sessions/${created.id}/start`, {
        method: "POST",
      });
      setSession(started);
      await refresh(started.id);
    });
  }

  function endSession() {
    if (
      !session ||
      !window.confirm(
        "End this exercise? The session will be closed and no further actions will be accepted.",
      )
    ) {
      return;
    }
    return run(async () => {
      const ended = await api<Session>(`/sessions/${session.id}/complete`, {
        method: "POST",
      });
      const finalEvaluation = await api<Evaluation>(
        `/sessions/${session.id}/evaluation`,
      );
      setCompletedExercise({
        sessionId: ended.id,
        scenarioName: selected?.name ?? ended.scenario_id,
        endedAtMinute: ended.simulation_time,
        totalScore: finalEvaluation.total_score,
        possibleScore: finalEvaluation.possible_score,
      });
      setSession(null);
      setRoles([]);
      setKnowledge({});
      setEvents([]);
      setAnswer("");
      setShareFact("");
      setDecisionText("");
      setRationale("");
    });
  }

  function advance(minutes: number) {
    return run(async () => {
      if (!session) return;
      await api(`/sessions/${session.id}/advance-time`, {
        method: "POST",
        body: JSON.stringify({ minutes }),
      });
      await refresh();
    });
  }

  function ask(event: FormEvent) {
    event.preventDefault();
    return run(async () => {
      if (!session) return;
      setAnswer("");
      setAnswerStreaming(true);
      const renderer = new SmoothedTextRenderer((character) => {
        setAnswer((current) => current + character);
      });
      try {
        for await (const event of streamApi(`/sessions/${session.id}/ask/stream`, {
          method: "POST",
          body: JSON.stringify({ target_role: targetRole, message: question }),
        })) {
          if (event.type === "delta") {
            renderer.enqueue(event.content);
          } else if (event.type === "error") {
            throw new Error(event.detail);
          }
        }
        await renderer.finish();
        setAnswerStreaming(false);
        await refresh();
      } finally {
        renderer.stop();
        setAnswerStreaming(false);
      }
    });
  }

  function share(event: FormEvent) {
    event.preventDefault();
    return run(async () => {
      if (!session || !selectedShareFact) return;
      await api(`/sessions/${session.id}/actions/share-fact`, {
        method: "POST",
        body: JSON.stringify({
          from_role: shareFrom,
          to_role: shareTo,
          fact_id: selectedShareFact,
        }),
      });
      await refresh();
    });
  }

  function handleScenarioSaved(updated: Scenario) {
    setScenarios((current) => current.map(
      (item) => item.id === updated.id ? updated : item,
    ));
    if (!updated.variants.some((item) => item.id === variantId)) {
      setVariantId(updated.variants[0]?.id ?? "");
    }
    if (!updated.decision_categories.some((item) => item.id === decisionCategory)) {
      setDecisionCategory(updated.decision_categories[0]?.id ?? "");
    }
  }

  function decide(event: FormEvent) {
    event.preventDefault();
    return run(async () => {
      if (!session) return;
      await api(`/sessions/${session.id}/actions/decision`, {
        method: "POST",
        body: JSON.stringify({
          actor_role: decisionActor,
          category: decisionCategory,
          decision: decisionText,
          confidence: selectedDecisionCategory?.captures_confidence
            ? decisionConfidence
            : null,
          rationale: rationale || null,
        }),
      });
      setDecisionText("");
      setRationale("");
      await refresh();
    });
  }

  return (
    <main>
      <header>
        <div>
          <span className="eyebrow">CYBER EXERCISE / CONTROL ROOM</span>
          <h1>Incident Room</h1>
        </div>
        <div className="clock">
          <span>SIMULATION TIME</span>
          <strong>{String(session?.simulation_time ?? 0).padStart(3, "0")} MIN</strong>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      {!session ? (
        <section className="launch panel">
          {completedExercise && (
            <div className="completion-notice" role="status">
              <span className="kicker">EXERCISE CLOSED</span>
              <strong>{completedExercise.scenarioName}</strong>
              <p>
                Ended at T+{completedExercise.endedAtMinute}. Final score{" "}
                {completedExercise.totalScore}/{completedExercise.possibleScore}.
              </p>
              <small>Audit reference {completedExercise.sessionId}</small>
            </div>
          )}
          {llmConfigured !== true && (
            <>
              <ModelConfiguration onConfigurationChange={setLlmConfigured} />
              <div className="launch-divider" />
            </>
          )}
          <div>
            <span className="kicker">NEW EXERCISE</span>
            <h2>Choose a deterministic incident track</h2>
            <p>{selected?.description ?? "Loading scenario catalog…"}</p>
          </div>
          <label>
            Scenario
            <select
              value={scenarioId}
              onChange={(event) => {
                const next = scenarios.find((item) => item.id === event.target.value);
                setScenarioId(event.target.value);
                setVariantId(next?.variants[0]?.id ?? "");
                setDecisionCategory(next?.decision_categories[0]?.id ?? "");
              }}
            >
              {scenarios.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <label>
            Variant
            <select value={variantId} onChange={(event) => setVariantId(event.target.value)}>
              {selected?.variants.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <button
            disabled={busy || !variantId || llmConfigured !== true}
            onClick={createSession}
          >
            Start exercise
          </button>
          {scenarioId && (
            <ScenarioEditor scenarioId={scenarioId} onSaved={handleScenarioSaved} />
          )}
          {llmConfigured === true && (
            <>
              <div className="launch-divider" />
              <ModelConfiguration onConfigurationChange={setLlmConfigured} />
            </>
          )}
        </section>
      ) : (
        <div className="grid">
          <section className="panel command">
            <div className="section-title">
              <span className="kicker">ACTIVE SESSION</span>
              <span className={`status ${session.status}`}>{session.status}</span>
            </div>
            <h2>{selected?.name}</h2>
            <p className="mono">{session.variant_id} / {session.id.slice(0, 8)}</p>
            <div className="button-row">
              <button disabled={busy || session.status !== "running"} onClick={() => advance(5)}>+5 min</button>
              <button disabled={busy || session.status !== "running"} onClick={() => advance(15)}>+15 min</button>
              <button className="exit-button" disabled={busy || session.status !== "running"} onClick={endSession}>End &amp; exit</button>
            </div>

            <form onSubmit={ask}>
              <label>
                Ask a role
                <select value={targetRole} onChange={(event) => setTargetRole(event.target.value)}>
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>{role.display_name}</option>
                  ))}
                </select>
              </label>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    if (!busy && question.trim()) {
                      event.currentTarget.form?.requestSubmit();
                    }
                  }
                }}
                rows={3}
                title="Press Enter to send, or Shift+Enter for a new line"
              />
              <button disabled={busy || !question.trim()}>Send question</button>
            </form>
            {(answer || answerStreaming) && (
              <div
                className={`answer-markdown${answerStreaming ? " is-streaming" : ""}`}
                aria-live="polite"
                aria-busy={answerStreaming}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
              </div>
            )}

            <div className="action-divider"><span>Structured actions</span></div>
            <div className="action-grid">
              <form className="action-card" onSubmit={share}>
                <span className="kicker">SHARE KNOWN FACT</span>
                <label>
                  From
                  <select value={shareFrom} onChange={(event) => setShareFrom(event.target.value)}>
                    {roles.map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                  </select>
                </label>
                <label>
                  To
                  <select value={shareTo} onChange={(event) => setShareTo(event.target.value)}>
                    {roles.map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                  </select>
                </label>
                <label>
                  Permitted fact
                  <select value={selectedShareFact} onChange={(event) => setShareFact(event.target.value)}>
                    {shareableFacts.length === 0 && <option value="">No known facts</option>}
                    {shareableFacts.map((fact) => (
                      <option key={fact.id} value={fact.id}>{fact.id} · {fact.statement}</option>
                    ))}
                  </select>
                </label>
                <button disabled={busy || !selectedShareFact || shareFrom === shareTo}>Share fact</button>
              </form>

              <form className="action-card" onSubmit={decide}>
                <span className="kicker">RECORD DECISION</span>
                <label>
                  Decision owner
                  <select value={decisionActor} onChange={(event) => setDecisionActor(event.target.value)}>
                    {roles.map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                  </select>
                </label>
                <label>
                  Category
                  <select value={decisionCategory} onChange={(event) => setDecisionCategory(event.target.value)}>
                    {selected?.decision_categories.map((category) => (
                      <option key={category.id} value={category.id}>{category.display_name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  What was decided?
                  <textarea
                    value={decisionText}
                    onChange={(event) => setDecisionText(event.target.value)}
                    placeholder="Describe the decision without choosing from a suggested action."
                    rows={3}
                  />
                </label>
                {selectedDecisionCategory?.captures_confidence && (
                  <label>
                    Conclusion confidence
                    <select value={decisionConfidence} onChange={(event) => setDecisionConfidence(event.target.value)}>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="confirmed">Confirmed</option>
                    </select>
                  </label>
                )}
                <label>
                  Rationale
                  <textarea value={rationale} onChange={(event) => setRationale(event.target.value)} rows={2} />
                </label>
                <button disabled={busy || !decisionCategory || !decisionText.trim()}>Record decision</button>
              </form>
            </div>
          </section>

          <section className="panel score">
            <span className="kicker">EVALUATION</span>
            <div className="score-number">
              <strong>—</strong>
            </div>
            <div className="debrief-locked">
              Detailed scoring is withheld until the exercise is closed.
            </div>
          </section>

          <section className="panel log">
            <div className="section-title">
              <span className="kicker">AUDIT LOG</span>
              <span>{events.length} EVENTS</span>
            </div>
            <div className="event-list">
              {[...events].reverse().map((item) => (
                <article key={item.id}>
                  <time>T+{String(item.simulation_time).padStart(3, "0")}</time>
                  <div>
                    <strong>{item.event_type.replaceAll("_", " ")}</strong>
                    <small>{item.actor_role ?? "system"}{item.target_role ? ` → ${item.target_role}` : ""}</small>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
