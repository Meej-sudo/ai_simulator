"use client";

import type { AuditEvent, Role } from "./types";
import { eventThread, initials } from "./ui";

type Props = {
  roles: Role[];
  events: AuditEvent[];
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
  activeThread,
  lastSeen,
  onSelect,
}: Props) {
  const bridgeUnread = unreadCount(events, "channel:bridge", lastSeen);

  return (
    <nav className="thread-rail" aria-label="Exercise conversations">
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
