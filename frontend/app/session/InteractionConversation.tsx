"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { StakeholderInteraction } from "./types";
import { initials } from "./ui";

type Props = {
  interaction: StakeholderInteraction;
  busy: boolean;
  onRespond: (interactionId: string, message: string) => Promise<boolean>;
};

export default function InteractionConversation({
  interaction,
  busy,
  onRespond,
}: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const waiting = interaction.status === "WAITING_FOR_TRAINEE";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [interaction.messages.length, interaction.responses.length]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message || !waiting) return;
    if (await onRespond(interaction.id, message)) setText("");
  }

  return (
    <>
      <div className="conversation-head interaction-head">
        <span className="avatar role-tone-3">
          {initials(interaction.actor_display_name)}
        </span>
        <span>
          <b>{interaction.actor_display_name}</b>
          <small>Stakeholder request · {waiting ? "Waiting for your response" : interaction.status === "RESOLVED" ? "Resolved" : "Response received"}</small>
        </span>
        <span className={`interaction-status ${interaction.status.toLowerCase()}`}>
          {interaction.status === "WAITING_FOR_TRAINEE" ? "Action needed" : interaction.status.toLowerCase()}
        </span>
      </div>

      <div className="conversation-stream interaction-stream">
        <div className="interaction-context-note">
          This stakeholder initiated the conversation. Respond as the external incident coordinator; no in-game seat is assigned to you.
        </div>
        {interaction.messages.map((message, index) => (
          <div className="interaction-exchange" key={message.id}>
            <article className="room-message">
              <span className="avatar role-tone-3">
                {initials(interaction.actor_display_name)}
              </span>
              <div className="message-body">
                <div className="message-meta">
                  <b>{interaction.actor_display_name}</b>
                  <time>T+{message.simulation_time}</time>
                </div>
                {message.kind === "follow_up" && (
                  <span className="follow-up-label">Follow-up</span>
                )}
                <div className="message-bubble markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.message}</ReactMarkdown>
                </div>
              </div>
            </article>
            {interaction.responses[index] && (
              <article className="room-message mine">
                <span className="avatar trainee-avatar">TR</span>
                <div className="message-body">
                  <div className="message-meta">
                    <b>You</b>
                    <time>T+{interaction.responses[index].simulation_time}</time>
                  </div>
                  <div className="message-bubble markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {interaction.responses[index].message}
                    </ReactMarkdown>
                  </div>
                </div>
              </article>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {waiting ? (
        <form className="room-composer interaction-composer" onSubmit={submit}>
          <div className="composer-entry">
            <textarea
              aria-label={`Respond to ${interaction.actor_display_name}`}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Write a concise response…"
              rows={3}
              value={text}
            />
            <button className="composer-send" disabled={busy || !text.trim()} type="submit">
              {busy ? "Sending…" : "Respond"}
            </button>
          </div>
          <p className="composer-hint">Your raw response and the current knowledge snapshot are retained in the exercise log.</p>
        </form>
      ) : (
        <div className="interaction-resolved">This stakeholder request is resolved.</div>
      )}
    </>
  );
}
