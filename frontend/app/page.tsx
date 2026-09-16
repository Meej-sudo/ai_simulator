"use client";

import { useEffect, useMemo, useState } from "react";

import ModelConfiguration from "./ModelConfiguration";
import ScenarioEditor from "./ScenarioEditor";
import { api } from "./api";
import SessionView from "./session/SessionView";
import type { Completion, Scenario, Session } from "./session/types";

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
      .then((items) => {
        setScenarios(items);
        const first = items[0];
        if (first) {
          setScenarioId(first.id);
          setVariantId(first.variants[0]?.id ?? "");
        }
        if (items.length === 0) {
          setError("No scenarios are available. Add a scenario before starting an exercise.");
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
