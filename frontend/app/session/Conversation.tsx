"use client";

import { useEffect, useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type {
  AuditEvent,
  Evidence,
  Role,
} from "./types";
import { asString, asStrings, initials, roleName } from "./ui";

type Props = {
  activeThread: string;
  roles: Role[];
  events: AuditEvent[];
  evidence: Evidence[];
  streamingText: string;
  streamingRole: string;
  pendingMessage: { threadId: string; text: string; citations: string[] } | null;
};

const bridgeTypes = new Set([
  "MESSAGE_POSTED",
  "SESSION_STARTED",
  "TIME_ADVANCED",
  "TIMELINE_EVENT_TRIGGERED",
  "DECISION_MADE",
  "ASSESSMENT_RECORDED",
  "ORGANIZATIONAL_PRESSURE_APPLIED",
  "INVESTIGATION_STARTED",
  "INVESTIGATION_COMPLETED",
]);

function EvidenceChips({
  ids,
  evidence,
}: {
  ids: string[];
  evidence: Evidence[];
}) {
  if (ids.length === 0) return null;
  return (
    <div className="message-chips">
      {ids.map((id) => {
        const item = evidence.find((candidate) => candidate.id === id);
        return (
          <span className="evidence-chip" key={id} title={item?.statement}>
            <i className={`reliability ${item?.reliability ?? ""}`} />
            {id}
          </span>
        );
      })}
    </div>
  );
}

function SystemEvent({ event }: { event: AuditEvent }) {
  let label = event.event_type.replaceAll("_", " ").toLowerCase();
  if (event.event_type === "SESSION_STARTED") label = "Exercise started";
  if (event.event_type === "TIME_ADVANCED") {
    label = `Simulation advanced to T+${event.payload.to_minute ?? event.simulation_time}`;
  }
  if (event.event_type === "TIMELINE_EVENT_TRIGGERED") {
    label = "A scheduled incident update became available";
  }
  return (
    <div className="system-message">
      <span />
      <time>T+{event.simulation_time}</time>
      {label}
      <span />
    </div>
  );
}

function StructuredEvent({
  event,
  roles,
}: {
  event: AuditEvent;
  roles: Role[];
}) {
  const type = event.event_type;
  const actor = roleName(roles, event.actor_role);
  const target = roleName(roles, event.target_role);
  const isDecision = type === "DECISION_MADE";
  const isAssessment = type === "ASSESSMENT_RECORDED";
  const isPressure = type === "ORGANIZATIONAL_PRESSURE_APPLIED";
  const isInvestigation = type.startsWith("INVESTIGATION_");
  const style = isDecision
    ? "decision"
    : isAssessment
      ? "assessment"
      : isPressure
        ? "pressure"
        : "investigation";

  let title = type.replaceAll("_", " ");
  let body = "";
  let sub = "";

  if (isDecision) {
    title = `Decision · ${asString(event.payload.decision_category)}`;
    body = asString(event.payload.decision);
    const confidence = asString(event.payload.confidence);
    sub = [actor, confidence && `Confidence: ${confidence}`].filter(Boolean).join(" · ");
  } else if (isAssessment) {
    title = `Assessment · ${asString(event.payload.hypothesis_label)}`;
    body = asString(event.payload.statement);
    sub = [actor, asString(event.payload.confidence)].filter(Boolean).join(" · ");
  } else if (isPressure) {
    title = `Organizational pressure · ${asString(event.payload.category).replaceAll("_", " ")}`;
    body = asString(event.payload.message);
    sub = [
      asString(event.payload.source_display_name),
      asString(event.payload.severity) && `${asString(event.payload.severity)} severity`,
    ].filter(Boolean).join(" · ");
  } else if (isInvestigation) {
    title =
      type === "INVESTIGATION_COMPLETED"
        ? "Investigation completed"
        : "Investigation started";
    const label = asString(event.payload.label);
    const request = asString(event.payload.request);
    body = label || request || asString(event.payload.investigation_id);
    const detail = label && request && request !== label ? request : "";
    sub = [`${actor} → ${target}`, detail].filter(Boolean).join(" · ");
  }

  return (
    <article className={`structured-record ${style}`}>
      <div className="record-label">
        <span>{title}</span>
        <time>T+{event.simulation_time}</time>
      </div>
      <p>{body}</p>
      <div className="record-sub">{sub}</div>
      {isInvestigation && type === "INVESTIGATION_STARTED" && (
        <div className="progress-track"><i /></div>
      )}
    </article>
  );
}

function Message({
  mine,
  name,
  index,
  time,
  text,
  citations,
  evidence,
  streaming = false,
}: {
  mine: boolean;
  name: string;
  index: number;
  time: number;
  text: string;
  citations: string[];
  evidence: Evidence[];
  streaming?: boolean;
}) {
  return (
    <article className={`room-message ${mine ? "mine" : ""}`}>
      <span className={`avatar ${mine ? "trainee-avatar" : `role-tone-${index % 4}`}`}>
        {mine ? "TR" : initials(name)}
      </span>
      <div className="message-body">
        <div className="message-meta">
          <b>{name}</b>
          <time>T+{time}</time>
        </div>
        <div className={`message-bubble markdown-body ${streaming ? "is-streaming" : ""}`}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
        <EvidenceChips ids={citations} evidence={evidence} />
      </div>
    </article>
  );
}

export default function Conversation({
  activeThread,
  roles,
  events,
  evidence,
  streamingText,
  streamingRole,
  pendingMessage,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const isBridge = activeThread === "channel:bridge";
  const roleId = isBridge ? "" : activeThread.replace(/^dm:/, "");
  const role = roles.find((item) => item.id === roleId);
  const roleIndex = Math.max(0, roles.findIndex((item) => item.id === roleId));

  const visible = useMemo(
    () =>
      events.filter((event) => {
        if (isBridge) {
          return (
            bridgeTypes.has(event.event_type) &&
            (event.event_type !== "MESSAGE_POSTED" ||
              event.payload.thread_id === "channel:bridge")
          );
        }
        return (
          (event.event_type === "QUESTION_ASKED" && event.target_role === roleId) ||
          (event.event_type === "ROLE_RESPONDED" && event.actor_role === roleId) ||
          (event.event_type === "EVIDENCE_SHARED" &&
            event.target_role === roleId) ||
          (event.event_type === "INVESTIGATION_STARTED" ||
            event.event_type === "INVESTIGATION_COMPLETED") &&
            (event.actor_role === roleId || event.target_role === roleId) ||
          (event.event_type === "MESSAGE_POSTED" &&
            event.payload.thread_id === activeThread)
        );
      }),
    [activeThread, events, isBridge, roleId],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [visible.length, streamingText]);

  return (
    <>
      <div className="conversation-head">
        {isBridge ? (
          <span className="thread-hash">#</span>
        ) : (
          <span className={`avatar role-tone-${roleIndex % 4}`}>
            {initials(role?.display_name ?? roleId)}
          </span>
        )}
        <span>
          <b>{isBridge ? "incident-bridge" : role?.display_name ?? roleId}</b>
          <small>
            {isBridge
              ? "Shared coordination channel for every incident role"
              : "Private conversation between the trainee and this simulated role"}
          </small>
        </span>
      </div>

      <div className="conversation-stream">
        {visible.length === 0 && (
          <div className="conversation-empty">
            <span>{isBridge ? "#" : initials(role?.display_name ?? roleId)}</span>
            <h2>{isBridge ? "Incident bridge" : role?.display_name}</h2>
            <p>
              {isBridge
                ? "Post coordination updates here, or log a structured action below."
                : "Ask this role what they know. Their answer is constrained to evidence currently known to them."}
            </p>
          </div>
        )}

        {visible.map((event) => {
          if (
            event.event_type === "SESSION_STARTED" ||
            event.event_type === "TIME_ADVANCED" ||
            event.event_type === "TIMELINE_EVENT_TRIGGERED"
          ) {
            return <SystemEvent event={event} key={event.id} />;
          }
          if (
            event.event_type === "DECISION_MADE" ||
            event.event_type === "ASSESSMENT_RECORDED" ||
            event.event_type === "ORGANIZATIONAL_PRESSURE_APPLIED" ||
            event.event_type === "INVESTIGATION_STARTED" ||
            event.event_type === "INVESTIGATION_COMPLETED"
          ) {
            return <StructuredEvent event={event} roles={roles} key={event.id} />;
          }
          if (event.event_type === "EVIDENCE_SHARED") {
            return (
              <div className="system-message" key={event.id}>
                <span />
                <time>T+{event.simulation_time}</time>
                Evidence shared with {roleName(roles, event.target_role)}
                <span />
              </div>
            );
          }
          if (event.event_type === "QUESTION_ASKED") {
            return (
              <Message
                mine
                name="You"
                index={0}
                time={event.simulation_time}
                text={asString(event.payload.message)}
                citations={asStrings(event.payload.cited_evidence_ids)}
                evidence={evidence}
                key={event.id}
              />
            );
          }
          if (event.event_type === "ROLE_RESPONDED") {
            return (
              <Message
                mine={false}
                name={roleName(roles, event.actor_role)}
                index={Math.max(0, roles.findIndex((item) => item.id === event.actor_role))}
                time={event.simulation_time}
                text={asString(event.payload.message)}
                citations={asStrings(event.payload.referenced_evidence_ids)}
                evidence={evidence}
                key={event.id}
              />
            );
          }
          return (
            <Message
              mine
              name="You"
              index={0}
              time={event.simulation_time}
              text={asString(event.payload.text)}
              citations={asStrings(event.payload.cited_evidence_ids)}
              evidence={evidence}
              key={event.id}
            />
          );
        })}

        {pendingMessage &&
          pendingMessage.threadId === activeThread &&
          !visible.some(
            (event) =>
              event.event_type === "QUESTION_ASKED" &&
              asString(event.payload.message) === pendingMessage.text,
          ) && (
            <Message
              mine
              name="You"
              index={0}
              time={events.at(-1)?.simulation_time ?? 0}
              text={pendingMessage.text}
              citations={pendingMessage.citations}
              evidence={evidence}
            />
          )}

        {streamingRole !== "" && streamingRole === roleId && (
          <Message
            mine={false}
            name={role?.display_name ?? roleId}
            index={roleIndex}
            time={events.at(-1)?.simulation_time ?? 0}
            text={streamingText}
            citations={[]}
            evidence={evidence}
            streaming
          />
        )}
        <div ref={endRef} />
      </div>
    </>
  );
}
