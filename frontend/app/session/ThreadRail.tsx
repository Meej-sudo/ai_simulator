"use client";

import type { AuditEvent, Role, StakeholderInteraction } from "./types";
import { eventThread, initials } from "./ui";

type Props = {
  roles: Role[];
  events: AuditEvent[];
  interactions: StakeholderInteraction[];
  activeThread: string;
  lastSeen: Record<string, number>;
  onSelect: (threadId: string) => void;
};

function unreadCount(
  events: AuditEvent[],
  threadId: string,
  lastSeen: Record<string, number>,
): number {
  const boundary = lastSeen[threadId] ?? 0;
  return events.filter(
    (event) =>
      event.sequence > boundary &&
      eventThread(event) === threadId &&
      event.event_type !== "QUESTION_ASKED",
  ).length;
}

export default function ThreadRail({
  roles,
  events,
  interactions,
  activeThread,
  lastSeen,
  onSelect,
}: Props) {
  const bridgeUnread = unreadCount(events, "channel:bridge", lastSeen);

  return (
    <nav className="thread-rail" aria-label="Exercise conversations">
      <div className="thread-group stakeholder-requests">
        <h3>Stakeholder requests</h3>
        {interactions.length === 0 ? (
          <p className="thread-empty">No requests yet</p>
        ) : (
          interactions.map((interaction) => {
            const threadId = `interaction:${interaction.id}`;
            const pending = interaction.status === "WAITING_FOR_TRAINEE";
            return (
              <button
                className="thread-button stakeholder-thread"
                aria-current={activeThread === threadId}
                key={interaction.id}
                onClick={() => onSelect(threadId)}
              >
                <span className="request-mark">!</span>
                <span className="thread-name">
                  {interaction.actor_display_name}
                  <small>{pending ? "Response requested" : interaction.status === "RESOLVED" ? "Resolved" : "Responded"}</small>
                </span>
                {pending && <span className="unread-count">1</span>}
              </button>
            );
          })
        )}
      </div>

      <div className="thread-group">
        <h3>Channels</h3>
        <button
          className="thread-button"
          aria-current={activeThread === "channel:bridge"}
          onClick={() => onSelect("channel:bridge")}
        >
          <span className="thread-hash">#</span>
          <span className="thread-name">incident-bridge</span>
          {bridgeUnread > 0 && <span className="unread-count">{bridgeUnread}</span>}
        </button>
      </div>

      <div className="thread-group">
        <h3>Direct messages</h3>
        {roles.map((role, index) => {
          const threadId = `dm:${role.id}`;
          const unread = unreadCount(events, threadId, lastSeen);
          return (
            <button
              className="thread-button"
              aria-current={activeThread === threadId}
              key={role.id}
              onClick={() => onSelect(threadId)}
            >
              <span className={`avatar role-tone-${index % 4}`}>
                {initials(role.display_name)}
              </span>
              <span className="thread-name">{role.display_name}</span>
              {unread > 0 && <span className="unread-count">{unread}</span>}
            </button>
          );
        })}
      </div>

      <div className="rail-note">
        <span>YOU ARE OUTSIDE THE ROLEPLAY</span>
        <p>Coordinate any role from the open thread. Actions are still attributed to in-game roles.</p>
      </div>
    </nav>
  );
}
