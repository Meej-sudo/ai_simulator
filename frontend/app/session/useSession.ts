"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import { api, streamApi } from "../api";
import type {
  AssessmentProjection,
  AuditEvent,
  Evidence,
  InvestigationRun,
  Knowledge,
  Role,
  Session,
  StakeholderInteraction,
} from "./types";

type State = {
  session: Session | null;
  roles: Role[];
  knowledge: Record<string, Evidence[]>;
  investigations: InvestigationRun[];
  assessments: AssessmentProjection;
  events: AuditEvent[];
  interactions: StakeholderInteraction[];
  activeThread: string;
  lastSeen: Record<string, number>;
  streamingText: string;
  streamingRole: string;
  pendingMessage: { threadId: string; text: string; citations: string[] } | null;
  busy: boolean;
  loading: boolean;
  error: string;
  notice: string;
  suggestions: { id: string; label: string }[];
};

type Action =
  | { type: "loading" }
  | {
      type: "loaded";
      payload: Pick<
        State,
        "session" | "roles" | "knowledge" | "investigations" | "assessments" | "events" | "interactions"
      >;
    }
  | { type: "session-updated"; session: Session }
  | { type: "thread"; threadId: string; sequence: number }
  | { type: "busy"; value: boolean }
  | { type: "error"; message: string }
  | { type: "stream-start"; roleId: string }
  | { type: "stream-delta"; content: string }
  | { type: "stream-replace"; content: string }
  | { type: "stream-end" }
  | { type: "pending-message"; message: { threadId: string; text: string; citations: string[] } }
  | { type: "clear-pending" }
  | { type: "suggestions"; items: { id: string; label: string }[] }
  | { type: "notice"; message: string };

const initialState: State = {
  session: null,
  roles: [],
  knowledge: {},
  investigations: [],
  assessments: { history: [], current: [] },
  events: [],
  interactions: [],
  activeThread: "channel:bridge",
  lastSeen: {},
  streamingText: "",
  streamingRole: "",
  pendingMessage: null,
  busy: false,
  loading: true,
  error: "",
  notice: "",
  suggestions: [],
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: "" };
    case "loaded": {
      const maxSequence = action.payload.events.at(-1)?.sequence ?? 0;
      return {
        ...state,
        ...action.payload,
        loading: false,
        lastSeen: {
          ...state.lastSeen,
          [state.activeThread]: Math.max(
            state.lastSeen[state.activeThread] ?? 0,
            maxSequence,
          ),
        },
      };
    }
    case "session-updated":
      return { ...state, session: action.session };
    case "thread":
      return {
        ...state,
        activeThread: action.threadId,
        lastSeen: { ...state.lastSeen, [action.threadId]: action.sequence },
      };
    case "busy":
      return { ...state, busy: action.value, notice: action.value ? "" : state.notice };
    case "error":
      return { ...state, error: action.message, loading: false, notice: "" };
    case "stream-start":
      return { ...state, streamingRole: action.roleId, streamingText: "" };
    case "stream-delta":
      return { ...state, streamingText: state.streamingText + action.content };
    case "stream-replace":
      // The validated reply differs from what streamed in, so show that
      // instead of appending to text the trainee should not keep reading.
      return { ...state, streamingText: action.content };
    case "stream-end":
      return { ...state, streamingRole: "", streamingText: "" };
    case "pending-message":
      return { ...state, pendingMessage: action.message };
    case "clear-pending":
      return { ...state, pendingMessage: null };
    case "suggestions":
      return { ...state, suggestions: action.items };
    case "notice":
      return { ...state, notice: action.message };
    default:
      return state;
  }
}

// Reveal pacing. A model can finish a reply far faster than anyone can read
// it, so words are released at a steady rate rather than as they arrive. The
// rate rises with the backlog so a long reply does not drag, but never past
// MAX_WORDS_PER_SECOND, which is what keeps a fast reply from flashing into
// place. A model slower than WORDS_PER_SECOND is never held back: there is no
// backlog to pace. Typical replies land around 18-25 words per second.
const WORDS_PER_SECOND = 18;
const MAX_WORDS_PER_SECOND = 45;
const CATCH_UP_SECONDS = 2.5;
const TICK_MS = 16;

export function useSession(sessionId: string) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const lastSequenceRef = useRef(0);
  const busyRef = useRef(false);
  const sessionRef = useRef<Session | null>(null);
  busyRef.current = state.busy || state.streamingRole !== "";
  sessionRef.current = state.session;

  const refresh = useCallback(async () => {
    const [session, roles, events, investigations, assessments, interactions] = await Promise.all([
      api<Session>(`/sessions/${sessionId}`),
      api<Role[]>(`/sessions/${sessionId}/roles`),
      api<AuditEvent[]>(`/sessions/${sessionId}/events`),
      api<InvestigationRun[]>(`/sessions/${sessionId}/investigations`),
      api<AssessmentProjection>(`/sessions/${sessionId}/assessments`),
      api<StakeholderInteraction[]>(`/sessions/${sessionId}/interactions`),
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
        interactions,
        knowledge: Object.fromEntries(pairs),
      },
    });
    lastSequenceRef.current = events.at(-1)?.sequence ?? 0;
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

  // Live sync: cheaply detect events produced elsewhere (another tab, an
  // instructor, or a completed investigation) and refresh the room when the
  // event log grew. Skipped while a local action or stream is in flight.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (busyRef.current || document.hidden) return;
      api<AuditEvent[]>(`/sessions/${sessionId}/events`)
        .then((events) => {
          const latest = events.at(-1)?.sequence ?? 0;
          if (latest !== lastSequenceRef.current) {
            lastSequenceRef.current = latest;
            return refresh();
          }
          return undefined;
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh, sessionId]);

  // The backend owns elapsed time. Polling only asks it to materialize whole
  // minutes; it persists the leftover seconds so a 10-second poll never loses
  // the remainder and a later tab/reload can catch up safely.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = sessionRef.current;
      if (
        busyRef.current ||
        document.hidden ||
        !current ||
        current.status !== "running" ||
        !current.clock_running
      ) return;

      api<Session>(`/sessions/${sessionId}/clock/sync`, { method: "POST" })
        .then((updated) => {
          const minuteChanged = updated.simulation_time !== current.simulation_time;
          sessionRef.current = updated;
          if (minuteChanged || updated.status !== current.status) return refresh();
          dispatch({ type: "session-updated", session: updated });
          return undefined;
        })
        .catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refresh, sessionId]);

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

  const pauseClock = useCallback(
    () =>
      run(async () => {
        await api(`/sessions/${sessionId}/clock/pause`, { method: "POST" });
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const resumeClock = useCallback(
    () =>
      run(async () => {
        await api(`/sessions/${sessionId}/clock/resume`, { method: "POST" });
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const sendMessage = useCallback(
    (text: string, citedEvidenceIds: string[]): Promise<boolean> => {
      if (state.activeThread === "channel:bridge") {
        return run(async () => {
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
          await refresh();
        });
      }
      const targetRole = state.activeThread.replace(/^dm:/, "");
      const threadId = state.activeThread;
      // Move the trainee's message into the thread immediately; the role's
      // reply streams in afterwards. The composer clears at once instead of
      // waiting for generation to finish.
      dispatch({
        type: "pending-message",
        message: { threadId, text, citations: citedEvidenceIds },
      });
      dispatch({ type: "busy", value: true });
      dispatch({ type: "error", message: "" });
      dispatch({ type: "stream-start", roleId: targetRole });
      void (async () => {
        // Arriving text is held here and released a few words at a time. One
        // dispatch per tick also coalesces a burst of tokens into a single
        // render instead of one render each.
        let queued = "";
        let credit = 0;
        let lastTick = 0;
        let streamEnded = false;
        let timer: ReturnType<typeof setTimeout> | null = null;
        let onDrained: (() => void) | null = null;

        // Words keep their trailing whitespace so each one fades in as a unit.
        // While more text may still arrive, the final word is held back: it
        // can still grow, and a half-word must not fade in on its own.
        const releasable = (): string[] => {
          const words = queued.match(/\S+\s*|\s+/g) ?? [];
          if (words.length === 0) return [];
          return streamEnded || /\s$/.test(queued) ? words : words.slice(0, -1);
        };

        const schedule = () => {
          if (!timer) timer = setTimeout(step, TICK_MS);
        };

        function step() {
          timer = null;
          const now = performance.now();
          // Cap the step so a throttled background tab does not bank credit.
          const elapsed = Math.min((now - lastTick) / 1000, 1);
          lastTick = now;

          const words = releasable();
          const rate = Math.min(
            MAX_WORDS_PER_SECOND,
            Math.max(WORDS_PER_SECOND, words.length / CATCH_UP_SECONDS),
          );
          credit += rate * elapsed;

          const take = Math.min(words.length, Math.floor(credit));
          if (take > 0) {
            credit -= take;
            const content = words.slice(0, take).join("");
            queued = queued.slice(content.length);
            dispatch({ type: "stream-delta", content });
          }

          if (releasable().length > 0) {
            schedule();
          } else if (streamEnded && onDrained) {
            const drained = onDrained;
            onDrained = null;
            drained();
          }
        }

        // Resolves once every word the model produced has been shown.
        const fullyRevealed = () =>
          new Promise<void>((resolve) => {
            if (releasable().length === 0) {
              resolve();
              return;
            }
            onDrained = resolve;
            schedule();
          });

        const discardQueued = () => {
          if (timer) clearTimeout(timer);
          timer = null;
          onDrained = null;
          queued = "";
          credit = 0;
        };

        try {
          let completed = false;
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
              queued += item.content;
              // Restart the clock whenever the pacer was idle, so a pause in
              // generation cannot bank credit and release a burst of words.
              if (!timer) lastTick = performance.now();
              schedule();
            } else if (item.type === "replace") {
              // Anything still queued belongs to the text being replaced.
              discardQueued();
              dispatch({ type: "stream-replace", content: item.content });
            } else if (item.type === "complete") {
              completed = true;
            } else if (item.type === "error") {
              throw new Error(item.detail);
            }
          }
          if (!completed) {
            throw new Error(
              "The reply was interrupted before it finished. Please retry.",
            );
          }
          // Let the last words finish appearing before the persisted message
          // replaces the streaming one, so the reply does not jump to its end.
          streamEnded = true;
          await fullyRevealed();
          await refresh();
        } catch (cause) {
          dispatch({
            type: "error",
            message:
              cause instanceof Error ? cause.message : "Unexpected error",
          });
        } finally {
          discardQueued();
          dispatch({ type: "stream-end" });
          dispatch({ type: "clear-pending" });
          dispatch({ type: "busy", value: false });
        }
      })();
      return Promise.resolve(true);
    },
    [refresh, run, sessionId, state.activeThread],
  );

  const shareEvidence = useCallback(
    (fromRole: string, toRole: string, evidenceId: string) =>
      run(async () => {
        await api(`/sessions/${sessionId}/actions/share-evidence`, {
          method: "POST",
          body: JSON.stringify({
            from_role: fromRole,
            to_role: toRole,
            evidence_id: evidenceId,
          }),
        });
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const requestWork = useCallback(
    (requesterRole: string, performerRole: string, request: string) =>
      run(async () => {
        dispatch({ type: "suggestions", items: [] });
        const result = await api<{
          accepted: boolean;
          reason: string;
          suggestions?: { id: string; label: string }[];
        }>(`/sessions/${sessionId}/investigations`, {
          method: "POST",
          body: JSON.stringify({
            requester_role: requesterRole,
            performer_role: performerRole,
            request,
          }),
        });
        if (!result.accepted) {
          dispatch({ type: "suggestions", items: result.suggestions ?? [] });
          throw new Error(result.reason);
        }
        await refresh();
      }),
    [refresh, run, sessionId],
  );

  const recordAssessment = useCallback(
    (actorRole: string, statement: string) =>
      run(async () => {
        const result = await api<{
          recorded: unknown[];
          message: string;
          warnings?: string[];
        }>(`/sessions/${sessionId}/assessments`, {
          method: "POST",
          body: JSON.stringify({ actor_role: actorRole, statement }),
        });
        if (result.warnings && result.warnings.length > 0) {
          dispatch({ type: "notice", message: result.warnings.join(" ") });
        }
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

  const respondToInteraction = useCallback(
    (interactionId: string, message: string) =>
      run(async () => {
        await api(`/sessions/${sessionId}/interactions/${interactionId}/respond`, {
          method: "POST",
          body: JSON.stringify({ message }),
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
    pauseClock,
    resumeClock,
    sendMessage,
    requestWork,
    shareEvidence,
    recordAssessment,
    recordDecision,
    respondToInteraction,
    refresh,
  };
}
