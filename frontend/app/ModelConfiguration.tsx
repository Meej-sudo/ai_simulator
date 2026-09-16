"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { api } from "./api";

type LLMConfiguration = {
  provider: string | null;
  model: string | null;
  configured: boolean;
  available_providers: string[];
};

type ModelList = {
  provider: string;
  models: string[];
};

type Props = {
  onConfigurationChange: (configured: boolean) => void;
};

const MODEL_POLL_INTERVAL_MS = 10_000;

export default function ModelConfiguration({ onConfigurationChange }: Props) {
  const [saved, setSaved] = useState<LLMConfiguration | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let active = true;
    api<LLMConfiguration>("/settings/llm")
      .then((configuration) => {
        if (!active) return;
        setSaved(configuration);
        setProvider(configuration.provider ?? "");
        setModel(configuration.model ?? "");
        onConfigurationChange(configuration.configured);
      })
      .catch((cause) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "Could not load AI settings");
        onConfigurationChange(false);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [onConfigurationChange]);

  useEffect(() => {
    if (provider !== "ollama") {
      setModels([]);
      setDiscovering(false);
      return;
    }

    let active = true;
    let timer: number | undefined;
    async function discover(showLoading: boolean) {
      if (showLoading) setDiscovering(true);
      try {
        const result = await api<ModelList>(
          `/settings/llm/models?provider=${encodeURIComponent(provider)}`,
        );
        if (!active) return;
        setModels(result.models);
        setError("");
      } catch (cause) {
        if (!active) return;
        setModels([]);
        setError(
          cause instanceof Error ? cause.message : "Could not discover Ollama models",
        );
      } finally {
        if (active) {
          if (showLoading) setDiscovering(false);
          timer = window.setTimeout(
            () => void discover(false),
            MODEL_POLL_INTERVAL_MS,
          );
        }
      }
    }

    void discover(true);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [provider]);

  const dirty = useMemo(
    () => provider !== (saved?.provider ?? "") || model !== (saved?.model ?? ""),
    [model, provider, saved],
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!provider || !model) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const configuration = await api<LLMConfiguration>("/settings/llm", {
        method: "PUT",
        body: JSON.stringify({ provider, model }),
      });
      setSaved(configuration);
      setProvider(configuration.provider ?? "");
      setModel(configuration.model ?? "");
      setSuccess("AI model saved and active for new exercise prompts.");
      onConfigurationChange(configuration.configured);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save AI settings");
    } finally {
      setSaving(false);
    }
  }

  const providerOptions = saved?.available_providers ?? ["ollama"];
  const selectedModelMissing = Boolean(model && !models.includes(model));

  return (
    <section className="model-configuration" aria-labelledby="model-configuration-title">
      <div className="model-heading">
        <div>
          <span className="kicker">AI MODEL CONFIGURATION</span>
          <h2 id="model-configuration-title">Choose the exercise model</h2>
          <p>
            Installed models are discovered from the selected provider every 10 seconds.
            Saving applies the model immediately and preserves it across restarts.
          </p>
        </div>
        {saved?.configured && (
          <span className="model-status">ACTIVE · {saved.provider}/{saved.model}</span>
        )}
      </div>

      {!loading && !saved?.configured && (
        <div className="configuration-warning" role="alert">
          No AI model is configured. Select and save a model before starting an exercise.
        </div>
      )}

      <form className="model-form" onSubmit={save}>
        <label>
          Provider
          <select
            value={provider}
            disabled={loading || saving}
            onChange={(event) => {
              setProvider(event.target.value);
              setModel("");
              setSuccess("");
            }}
          >
            <option value="">Select a provider</option>
            {providerOptions.map((item) => (
              <option key={item} value={item}>
                {item === "ollama" ? "Ollama" : item}
              </option>
            ))}
          </select>
        </label>

        <label>
          Model
          <select
            value={model}
            disabled={!provider || discovering || saving}
            onChange={(event) => {
              setModel(event.target.value);
              setSuccess("");
            }}
          >
            <option value="">
              {discovering ? "Discovering available models…" : "Select a model"}
            </option>
            {selectedModelMissing && (
              <option value={model}>{model} · currently unavailable</option>
            )}
            {models.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

        <button disabled={loading || saving || !provider || !model || !dirty}>
          {saving ? "Saving…" : "Save model"}
        </button>
      </form>

      {provider === "ollama" && !discovering && models.length === 0 && !error && (
        <div className="model-note">Ollama reported no installed models.</div>
      )}
      {error && <div className="editor-error">{error}</div>}
      {success && <div className="editor-success">{success}</div>}
    </section>
  );
}
