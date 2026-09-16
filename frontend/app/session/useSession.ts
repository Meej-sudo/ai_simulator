"use client";

import { useCallback, useEffect, useMemo, useReducer } from "react";

import { api, streamApi } from "../api";
import type {
  AssessmentProjection,
  AuditEvent,
  Evidence,
  InvestigationRun,
  Knowledge,
  Role,
  Session,
} from "./types";

type State = {
  session: Session | null;
  roles: Role[];
  knowledge: Record<string, Evidence[]>;
  investigations: InvestigationRun[];
  assessments: AssessmentProjection;
  events: AuditEvent[];
  activeThread: string;
  lastSeen: Record<string, number>;
  streamingText: string;
  streamingRole: string;
  busy: boolean;
  loading: boolean;
  error: string;
};

type Action =
  | { type: "loading" }
  | {
      type: "loaded";
      payload: Pick<
        State,
        "session" | "roles" | "knowledge" | "investigations" | "assessments" | "events"
      >;
    }
  | { type: "thread"; threadId: string; sequence: number }
  | { type: "busy"; value: boolean }
  | { type: "error"; message: string }
  | { type: "stream-start"; roleId: string }
  | { type: "stream-delta"; content: string }
  | { type: "stream-end" };

const initialState: State = {
  session: null,
  roles: [],
  knowledge: {},
  investigations: [],
  assessments: { history: [], current: [] },
  events: [],
  activeThread: "channel:bridge",
  lastSeen: {},
  streamingText: "",
  streamingRole: "",
  busy: false,
  loading: true,
  error: "",
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: "" };
    case "loaded": {
      const maxSequence = action.payload.events.at(-1)?.sequence ?? 0;
      const firstLoad = state.session === null;
      return {
        ...state,
        ...action.payload,
        loading: false,
        lastSeen: firstLoad
          ? { ...state.lastSeen, [state.activeThread]: maxSequence }
          : state.lastSeen,
      };
    }
    case "thread":
      return {
        ...state,
        activeThread: action.threadId,
        lastSeen: { ...state.lastSeen, [action.threadId]: action.sequence },
      };
    case "busy":
      return { ...state, busy: action.value };
    case "error":
      return { ...state, error: action.message, loading: false };
    case "stream-start":
      return { ...state, streamingRole: action.roleId, streamingText: "" };
    case "stream-delta":
      return { ...state, streamingText: state.streamingText + action.content };
    case "stream-end":
      return { ...state, streamingRole: "", streamingText: "" };
    default:
      return state;
  }
}

export function useSession(sessionId: string) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const refresh = useCallback(async () => {
    const [session, roles, events, investigations, assessments] = await Promise.all([
      api<Session>(`/sessions/${sessionId}`),
      api<Role[]>(`/sessions/${sessionId}/roles`),
      api<AuditEvent[]>(`/sessions/${sessionId}/events`),
      api<InvestigationRun[]>(`/sessions/${sessionId}/investigations`),
      api<AssessmentProjection>(`/sessions/${sessionId}/assessments`),
    ]);
    const pairs = await Promise.all(
      roles.map(async (role) => {
        const result = await api<Knowledge>(
          `/sessions/${sessionId}/roles/${role.id}/knowledge`,
        );
        const evidence: Evidence[] = [
          ...result.observations.map((item) => ({
            ...item,
            kind: "observation" as const,
          })),
          ...result.findings.map((item) => ({
            ...item,
            kind: "finding" as const,
          })),
        ];
        return [role.id, evidence] as const;
      }),
    );
    dispatch({
      type: "loaded",
      payload: {
        session,
        roles,
        events,
        investigations,
        assessments,
        knowledge: Object.fromEntries(pairs),
      },
    });
  }, [sessionId]);

  useEffect(() => {
    dispatch({ type: "loading" });
    refresh().catch((cause) => {
      dispatch({
        type: "error",
        message: cause instanceof Error ? cause.message : "Could not load the exercise.",
      });
    });
  }, [refresh]);

  const run = useCallback(
    async (operation: () => Promise<void>): Promise<boolean> => {
      dispatch({ type: "busy", value: true });
      dispatch({ type: "error", message: "" });
      try {
        await operation();
        return true;
      } catch (cause) {
        dispatch({
          type: "error",
          message: cause instanceof Error ? cause.message : "Unexpected error",
        });
        return false;
      } finally {
        dispatch({ type: "busy", value: false });
      }
    },
    [],
  );

  const selectThread = useCallback(
    (threadId: string) => {
      dispatch({
        type: "thread",
        threadId,
        sequence: state.events.at(-1)?.sequence ?? 0,
      });
    },
    [state.events],
  );

  const advance = useCallback(
    (minutes: number) =>
      run(async () => {
        await api(`/sessions/${sessionId}/advance-time`, {
          method: "POST",
          body: JSON.stringify({ minutes }),
        });
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const sendMessage = useCallback(
    (text: string, citedEvidenceIds: string[]) =>
      run(async () => {
        if (state.activeThread === "channel:bridge") {
          await api(
            `/sessions/${sessionId}/threads/${encodeURIComponent(state.activeThread)}/messages`,
            {
              method: "POST",
              body: JSON.stringify({
                text,
                cited_evidence_ids: citedEvidenceIds,
              }),
            },
          );
        } else {
          const targetRole = state.activeThread.replace(/^dm:/, "");
          dispatch({ type: "stream-start", roleId: targetRole });
          try {
            for await (const item of streamApi(
              `/sessions/${sessionId}/ask/stream`,
              {
                method: "POST",
                body: JSON.stringify({
                  target_role: targetRole,
                  message: text,
                  cited_evidence_ids: citedEvidenceIds,
                }),
              },
            )) {
              if (item.type === "delta") {
                dispatch({ type: "stream-delta", content: item.content });
              } else if (item.type === "error") {
                throw new Error(item.detail);
              }
            }
          } finally {
            dispatch({ type: "stream-end" });
          }
        }
        await refresh();
      }),
    [refresh, run, sessionId, state.activeThread],
  );

  const requestWork = useCallback(
    (requesterRole: string, performerRole: string, request: string) =>
      run(async () => {
        const result = await api<{ accepted: boolean; reason: string }>(
          `/sessions/${sessionId}/investigations`,
          {
            method: "POST",
            body: JSON.stringify({
              requester_role: requesterRole,
              performer_role: performerRole,
              request,
            }),
          },
        );
        if (!result.accepted) throw new Error(result.reason);
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const recordAssessment = useCallback(
    (actorRole: string, statement: string) =>
      run(async () => {
        const result = await api<{ recorded: unknown[]; message: string }>(
          `/sessions/${sessionId}/assessments`,
          {
            method: "POST",
            body: JSON.stringify({ actor_role: actorRole, statement }),
          },
        );
        if (result.recorded.length === 0) throw new Error(result.message);
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const recordDecision = useCallback(
    (
      actorRole: string,
      category: string,
      decision: string,
      confidence: string | null,
      rationale: string | null,
    ) =>
      run(async () => {
        await api(`/sessions/${sessionId}/actions/decision`, {
          method: "POST",
          body: JSON.stringify({
            actor_role: actorRole,
            category,
            decision,
            confidence,
            rationale,
          }),
        });
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const discoveredEvidence = useMemo(() => {
    const evidence = new Map<string, Evidence>();
    for (const [roleId, items] of Object.entries(state.knowledge)) {
      for (const item of items) {
        const existing = evidence.get(item.id);
        if (existing) {
          existing.holders = [...(existing.holders ?? []), roleId];
        } else {
          evidence.set(item.id, { ...item, holders: [roleId] });
        }
      }
    }
    return [...evidence.values()].sort((left, right) =>
      left.id.localeCompare(right.id),
    );
  }, [state.knowledge]);

  return {
    state,
    discoveredEvidence,
    selectThread,
    advance,
    sendMessage,
    requestWork,
    recordAssessment,
    recordDecision,
    refresh,
  };
}
