"use client";

import { FormEvent, useMemo, useState } from "react";

import type {
  ComposerMode,
  DecisionCategory,
  Evidence,
  Role,
} from "./types";

type Props = {
  activeThread: string;
  roles: Role[];
  evidence: Evidence[];
  categories: DecisionCategory[];
  busy: boolean;
  suggestions: { id: string; label: string }[];
  onMessage: (text: string, citedEvidenceIds: string[]) => Promise<boolean>;
  onInvestigate: (
    requesterRole: string,
    performerRole: string,
    request: string,
  ) => Promise<boolean>;
  onAssess: (actorRole: string, statement: string) => Promise<boolean>;
  onDecide: (
    actorRole: string,
    category: string,
    decision: string,
    confidence: string | null,
    rationale: string | null,
  ) => Promise<boolean>;
};

const modes: Array<{ id: ComposerMode; label: string }> = [
  { id: "message", label: "Message" },
  { id: "investigate", label: "Request work" },
  { id: "assess", label: "Log assessment" },
  { id: "decide", label: "Log decision" },
];

export default function Composer({
  activeThread,
  roles,
  evidence,
  categories,
  busy,
  suggestions,
  onMessage,
  onInvestigate,
  onAssess,
  onDecide,
}: Props) {
  const [mode, setMode] = useState<ComposerMode>("message");
  const [text, setText] = useState("");
  const [actorRole, setActorRole] = useState(roles[0]?.id ?? "");
  const [performerRole, setPerformerRole] = useState(
    activeThread.startsWith("dm:") ? activeThread.slice(3) : roles[0]?.id ?? "",
  );
  const [category, setCategory] = useState(categories[0]?.id ?? "");
  const [confidence, setConfidence] = useState("medium");
  const [citations, setCitations] = useState<string[]>([]);

  const selectedCategory = useMemo(
    () => categories.find((item) => item.id === category),
    [categories, category],
  );
  const selectedRole = activeThread.startsWith("dm:")
    ? roles.find((role) => role.id === activeThread.slice(3))
    : null;
  // Free-text posting to the incident bridge is hidden for now: the entry box
  // and Send button are not rendered on the bridge thread. The message mode,
  // onMessage handler, and backend route are untouched; delete this flag and
  // its uses to bring the bridge input back.
  const bridgeChatHidden = mode === "message" && !selectedRole;

  function toggleCitation(evidenceId: string) {
    setCitations((current) =>
      current.includes(evidenceId)
        ? current.filter((id) => id !== evidenceId)
        : [...current, evidenceId],
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value || bridgeChatHidden) return;
    const citedSuffix =
      citations.length > 0 ? ` Evidence cited: ${citations.join(", ")}.` : "";

    let accepted = false;
    if (mode === "message") {
      accepted = await onMessage(value, citations);
    } else if (mode === "investigate") {
      accepted = await onInvestigate(
        actorRole,
        performerRole,
        value + citedSuffix,
      );
    } else if (mode === "assess") {
      accepted = await onAssess(actorRole, value + citedSuffix);
    } else {
      accepted = await onDecide(
        actorRole,
        category,
        value,
        selectedCategory?.captures_confidence ? confidence : null,
        citations.length > 0 ? `Evidence cited: ${citations.join(", ")}.` : null,
      );
    }

    if (accepted) {
      setText("");
      setCitations([]);
    }
  }

  const submitLabels: Record<ComposerMode, string> = {
    message: "Send",
    investigate: "Request",
    assess: "Record",
    decide: "Record",
  };
  const placeholders: Record<ComposerMode, string> = {
    message:
      selectedRole
        ? `Ask ${selectedRole.display_name} what they know…`
        : "Post an update to the incident bridge…",
    investigate: "Describe the evidence or technical question to investigate…",
    assess: "State a hypothesis, confidence, and evidence basis…",
    decide: "Describe the decision being made…",
  };

  return (
    <form className="room-composer" onSubmit={submit}>
      <div className="composer-modes" role="group" aria-label="Composer mode">
        {modes.map((item) => (
          <button
            aria-pressed={mode === item.id}
            key={item.id}
            onClick={() => setMode(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>

      {mode !== "message" && (
        <div className="composer-options">
          <label>
            Acting role
            <select
              value={actorRole}
              onChange={(event) => setActorRole(event.target.value)}
            >
              {roles.map((role) => (
                <option key={role.id} value={role.id}>{role.display_name}</option>
              ))}
            </select>
          </label>

          {mode === "investigate" && (
            <label>
              Assign to
              <select
                value={performerRole}
                onChange={(event) => setPerformerRole(event.target.value)}
              >
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>{role.display_name}</option>
                ))}
              </select>
            </label>
          )}

          {mode === "decide" && (
            <>
              <label>
                Category
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {categories.map((item) => (
                    <option key={item.id} value={item.id}>{item.display_name}</option>
                  ))}
                </select>
              </label>
              {selectedCategory?.captures_confidence && (
                <label>
                  Confidence
                  <select
                    value={confidence}
                    onChange={(event) => setConfidence(event.target.value)}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="confirmed">Confirmed</option>
                  </select>
                </label>
              )}
            </>
          )}
        </div>
      )}

      {mode === "investigate" && suggestions.length > 0 && (
        <div className="composer-suggestions" aria-label="Available investigations">
          <span>Available work:</span>
          {suggestions.map((item) => (
            <button
              key={item.id}
              onClick={() => setText(item.label)}
              title={item.label}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      {evidence.length > 0 && (
        <div className="citation-strip" aria-label="Cite discovered evidence">
          <span>Cite</span>
          {evidence.map((item) => (
            <button
              aria-pressed={citations.includes(item.id)}
              key={item.id}
              onClick={() => toggleCitation(item.id)}
              title={item.statement}
              type="button"
            >
              {item.id}
            </button>
          ))}
        </div>
      )}

      {bridgeChatHidden ? (
        <p className="composer-hint">
          Open a role’s direct message to ask a question, or use the other tabs
          to request work, record an assessment, or log a decision.
        </p>
      ) : (
        <>
          <div className="composer-entry">
            <textarea
              aria-label={modes.find((item) => item.id === mode)?.label}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={placeholders[mode]}
              rows={2}
              value={text}
            />
            <button
              className="composer-send"
              disabled={
                busy ||
                !text.trim() ||
                (mode !== "message" && !actorRole) ||
                (mode === "investigate" && !performerRole) ||
                (mode === "decide" && !category)
              }
              type="submit"
            >
              {busy ? "Working…" : submitLabels[mode]}
            </button>
          </div>
          <p className="composer-hint">
            Enter to submit · Shift+Enter for a new line
            {mode === "message" && selectedRole
              ? " · replies use only that role’s current evidence"
              : ""}
          </p>
        </>
      )}
    </form>
  );
}
