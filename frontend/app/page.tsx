"use client";

import { useEffect, useMemo, useState } from "react";

import ModelConfiguration from "./ModelConfiguration";
import ScenarioEditor from "./ScenarioEditor";
import { api } from "./api";
import SessionView from "./session/SessionView";
import type { Completion, Evaluation, Scenario, Session } from "./session/types";

const ACTIVE_SESSION_KEY = "incident-room-active-session";

export default function Home() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [variantId, setVariantId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [completion, setCompletion] = useState<Completion | null>(null);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(
    () => scenarios.find((scenario) => scenario.id === scenarioId),
    [scenarioId, scenarios],
  );

  useEffect(() => {
    api<Scenario[]>("/scenarios")
      .then(async (items) => {
        setScenarios(items);
        const first = items[0];
        if (first) {
          setScenarioId(first.id);
          setVariantId(first.variants[0]?.id ?? "");
        }
        if (items.length === 0) {
          setError("No scenarios are available. Add a scenario before starting an exercise.");
        }
        // Rejoin an exercise that is still running after a page reload, or show
        // the debrief for one that closed while the tab was away. The time limit
        // completes sessions on its own, so a reload must not strand the trainee
        // at the launcher with the result unreachable.
        const savedId = window.localStorage.getItem(ACTIVE_SESSION_KEY);
        if (!savedId) return;
        try {
          const saved = await api<Session>(`/sessions/${savedId}`);
          const scenario = items.find((item) => item.id === saved.scenario_id);
          if (scenario && saved.status === "running") {
            setScenarioId(scenario.id);
            setVariantId(saved.variant_id);
            setSessionId(saved.id);
            return;
          }
          if (scenario && saved.status === "completed") {
            const evaluation = await api<Evaluation>(
              `/sessions/${saved.id}/evaluation`,
            );
            setCompletion({
              sessionId: saved.id,
              scenarioName: scenario.name,
              endedAtMinute: saved.simulation_time,
              totalScore: evaluation.total_score,
              possibleScore: evaluation.possible_score,
              rules: evaluation.rules ?? [],
            });
          }
          window.localStorage.removeItem(ACTIVE_SESSION_KEY);
        } catch {
          window.localStorage.removeItem(ACTIVE_SESSION_KEY);
        }
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "Could not load scenarios.");
      })
      .finally(() => setCatalogLoading(false));
  }, []);

  async function startExercise() {
    if (!selected || !variantId) return;
    setBusy(true);
    setError("");
    setCompletion(null);
    try {
      const created = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({
          scenario_id: selected.id,
          variant_id: variantId,
        }),
      });
      const started = await api<Session>(`/sessions/${created.id}/start`, {
        method: "POST",
      });
      window.localStorage.setItem(ACTIVE_SESSION_KEY, started.id);
      setSessionId(started.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start the exercise.");
    } finally {
      setBusy(false);
    }
  }

  function handleScenarioSaved(updated: Scenario) {
    setScenarios((current) =>
      current.map((scenario) => (scenario.id === updated.id ? updated : scenario)),
    );
    if (!updated.variants.some((variant) => variant.id === variantId)) {
      setVariantId(updated.variants[0]?.id ?? "");
    }
  }

  if (sessionId && selected) {
    return (
      <SessionView
        onComplete={(result) => {
          window.localStorage.removeItem(ACTIVE_SESSION_KEY);
          setCompletion(result);
          setSessionId("");
        }}
        scenario={selected}
        sessionId={sessionId}
      />
    );
  }

  return (
    <main className="launch-shell">
      <header className="launch-header">
        <div>
          <span className="eyebrow">CYBER EXERCISE / CONTROL ROOM</span>
          <h1>Incident Room</h1>
        </div>
        <div className="launch-identity">
          <b>External trainee</b>
          <span>Coordinate the roles. You do not play one.</span>
        </div>
      </header>

      {error && <div className="error" role="alert">{error}</div>}

      <section className="launch panel">
        {completion && (
          <div className="completion-notice" role="status">
            <span className="kicker">EXERCISE CLOSED</span>
            <strong>{completion.scenarioName}</strong>
            <p>
              Ended at T+{completion.endedAtMinute}. Final score{" "}
              {completion.totalScore}/{completion.possibleScore}.
            </p>
            {completion.rules.length > 0 && (
              <ul className="debrief-list">
                {completion.rules.map((rule) => (
                  <li
                    className={
                      rule.awarded_points >= rule.possible_points
                        ? "debrief-hit"
                        : rule.awarded_points > 0
                          ? "debrief-partial"
                          : "debrief-miss"
                    }
                    key={rule.rule_id}
                  >
                    <b>
                      {rule.awarded_points}/{rule.possible_points} —{" "}
                      {rule.description}
                    </b>
                    <span>
                      Expected: {rule.expected_action}
                      {rule.expected_by_minute !== null
                        ? ` by T+${rule.expected_by_minute}`
                        : ""}
                      {" · "}
                      {rule.actual_action
                        ? `Actual: ${rule.actual_action}${
                            rule.actual_minute !== null
                              ? ` at T+${rule.actual_minute}`
                              : ""
                          }`
                        : "No matching action recorded."}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <small>Audit reference {completion.sessionId}</small>
          </div>
        )}

        {llmConfigured !== true && (
          <>
            <ModelConfiguration onConfigurationChange={setLlmConfigured} />
            <div className="launch-divider" />
          </>
        )}

        <div className="launch-copy">
          <span className="kicker">NEW EXERCISE</span>
          <h2>Choose an incident track</h2>
          <p>
            {catalogLoading
              ? "Loading scenario catalog…"
              : selected?.description ??
                "The scenario catalog is empty or could not be loaded."}
          </p>
        </div>

        <div className="launch-fields">
          <label>
            Scenario
            <select
              disabled={catalogLoading || scenarios.length === 0}
              onChange={(event) => {
                const next = scenarios.find(
                  (scenario) => scenario.id === event.target.value,
                );
                setScenarioId(event.target.value);
                setVariantId(next?.variants[0]?.id ?? "");
              }}
              value={scenarioId}
            >
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Variant
            <select
              disabled={!selected}
              onChange={(event) => setVariantId(event.target.value)}
              value={variantId}
            >
              {selected?.variants.map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {variant.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          className="launch-start"
          disabled={busy || !variantId || llmConfigured !== true}
          onClick={startExercise}
        >
          {busy ? "Opening room…" : "Start exercise"}
        </button>

        {scenarioId && (
          <ScenarioEditor
            onSaved={handleScenarioSaved}
            scenarioId={scenarioId}
          />
        )}

        {llmConfigured === true && (
          <>
            <div className="launch-divider" />
            <ModelConfiguration onConfigurationChange={setLlmConfigured} />
          </>
        )}
      </section>
    </main>
  );
}
