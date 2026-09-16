import type { AuditEvent, Role } from "./types";

export function roleName(roles: Role[], roleId?: string): string {
  return roles.find((role) => role.id === roleId)?.display_name ?? roleId ?? "System";
}

export function initials(label: string): string {
  return label
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}

export function eventThread(event: AuditEvent): string | null {
  if (event.event_type === "MESSAGE_POSTED") {
    return String(event.payload.thread_id ?? "");
  }
  if (event.event_type === "QUESTION_ASKED" && event.target_role) {
    return `dm:${event.target_role}`;
  }
  if (event.event_type === "ROLE_RESPONDED" && event.actor_role) {
    return `dm:${event.actor_role}`;
  }
  return null;
}

export function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function asStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
