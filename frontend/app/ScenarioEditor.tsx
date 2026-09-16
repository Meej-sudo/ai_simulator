"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import ScenarioForm from "./ScenarioForm";
import type { AuthoringResponse, ScenarioDocument, ScenarioSummary } from "./scenario-types";

type Props = {
  scenarioId: string;
  onSaved: (scenario: ScenarioSummary) => void;
};

export default function ScenarioEditor({ scenarioId, onSaved }: Props) {
  const [open, setOpen] = useState(false);
  const [document, setDocument] = useState<ScenarioDocument | null>(null);
  const [savedDocument, setSavedDocument] = useState<ScenarioDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const dirty = useMemo(
    () => document !== null && savedDocument !== null
      && JSON.stringify(document) !== JSON.stringify(savedDocument),
    [document, savedDocument],
  );

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setNotice("");
    api<AuthoringResponse>(`/scenarios/${scenarioId}/authoring`)
      .then((result) => {
        if (cancelled) return;
        setDocument(result.document);
        setSavedDocument(result.document);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not load scenario form");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, scenarioId]);

  async function reload() {
    if (dirty && !window.confirm("Discard all unsaved form changes?")) return;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const result = await api<AuthoringResponse>(`/scenarios/${scenarioId}/authoring`);
      setDocument(result.document);
      setSavedDocument(result.document);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reload scenario form");
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!document || !dirty) return;
    if (!window.confirm("Validate and save this scenario?")) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await api<AuthoringResponse>(`/scenarios/${scenarioId}/authoring`, {
        method: "PUT",
        body: JSON.stringify({ document }),
      });
      setDocument(result.document);
      setSavedDocument(result.document);
      setNotice("Scenario validated and saved to YAML.");
      onSaved(result.scenario);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save scenario");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="scenario-editor">
      <div className="editor-heading">
        <div>
          <span className="kicker">SCENARIO AUTHORING</span>
          <strong>Edit scenario with forms</strong>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => {
            if (open && dirty && !window.confirm("Close and discard unsaved changes?")) {
              return;
            }
            setOpen(!open);
          }}
        >
          {open ? "Close editor" : "Open editor"}
        </button>
      </div>

      {open && (
        <div className="editor-body">
          <p className="editor-warning">
            Changes are stored in the two-file scenario package after the complete scenario passes
            validation. Update related IDs and references together before saving.
          </p>

          {loading && <div className="editor-state">Loading scenario…</div>}
          {error && <div className="editor-error" role="alert">{error}</div>}
          {notice && <div className="editor-success" role="status">{notice}</div>}

          {!loading && document && (
            <>
              <ScenarioForm document={document} onChange={setDocument} />
              <div className="editor-actions">
                <span className={dirty ? "dirty" : "saved"}>
                  {dirty ? "Unsaved changes" : "All changes saved"}
                </span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={loading || saving}
                  onClick={reload}
                >
                  Reset changes
                </button>
                <button type="button" disabled={!dirty || saving} onClick={save}>
                  {saving ? "Validating…" : "Save scenario"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
