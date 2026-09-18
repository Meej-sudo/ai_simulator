"use client";

import { useState } from "react";

import { api } from "../api";
import Composer from "./Composer";
import ContextRail from "./ContextRail";
import Conversation from "./Conversation";
import InteractionConversation from "./InteractionConversation";
import ThreadRail from "./ThreadRail";
import TopBar from "./TopBar";
import type { Completion, Evaluation, Scenario, Session } from "./types";
import { useSession } from "./useSession";

type Props = {
  sessionId: string;
  scenario: Scenario;
  onComplete: (completion: Completion) => void;
};

export default function SessionView({
  sessionId,
  scenario,
  onComplete,
}: Props) {
  const controller = useSession(sessionId);
  const { state, discoveredEvidence } = controller;
  const [ending, setEnding] = useState(false);
  const activeInteraction = state.activeThread.startsWith("interaction:")
    ? state.interactions.find(
        (item) => item.id === state.activeThread.slice("interaction:".length),
      )
    : undefined;

  async function endExercise() {
    if (
      !state.session ||
      !window.confirm(
        "End this exercise? The session will close and no more actions can be recorded.",
      )
    ) {
      return;
    }
    setEnding(true);
    try {
      const ended = await api<Session>(`/sessions/${sessionId}/complete`, {
        method: "POST",
      });
      const evaluation = await api<Evaluation>(
        `/sessions/${sessionId}/evaluation`,
      );
      onComplete({
        sessionId: ended.id,
        scenarioName: scenario.name,
        endedAtMinute: ended.simulation_time,
        totalScore: evaluation.total_score,
        possibleScore: evaluation.possible_score,
        rules: evaluation.rules ?? [],
      });
    } finally {
      setEnding(false);
    }
  }

  if (state.loading && !state.session) {
    return (
      <main className="room-loading">
        <span className="kicker">OPENING INCIDENT ROOM</span>
        <h1>Preparing conversations…</h1>
      </main>
    );
  }

  if (!state.session) {
    return (
      <main className="room-loading">
        <span className="kicker">SESSION UNAVAILABLE</span>
        <h1>The incident room could not be loaded.</h1>
        {state.error && <div className="room-error">{state.error}</div>}
      </main>
    );
  }

  return (
    <div className="incident-room">
      <TopBar
        busy={state.busy || ending}
        onAdvance={controller.advance}
        onEnd={endExercise}
        scenario={scenario}
        session={state.session}
      />
      {state.error && (
        <div className="room-error room-error-floating" role="alert">
          {state.error}
        </div>
      )}
      {!state.error && state.notice && (
        <div className="room-notice room-error-floating" role="status">
          {state.notice}
        </div>
      )}
      <div className="room-panes">
        <ThreadRail
          activeThread={state.activeThread}
          events={state.events}
          interactions={state.interactions}
          lastSeen={state.lastSeen}
          onSelect={controller.selectThread}
          roles={state.roles}
        />
        <main className="conversation-pane">
<<<<<<< HEAD
          {activeInteraction ? (
            <InteractionConversation
              busy={state.busy}
              interaction={activeInteraction}
              onRespond={controller.respondToInteraction}
            />
          ) : (
            <>
              <Conversation
                activeThread={state.activeThread}
                events={state.events}
                evidence={discoveredEvidence}
                roles={state.roles}
                streamingRole={state.streamingRole}
                streamingText={state.streamingText}
              />
              <Composer
                activeThread={state.activeThread}
                busy={state.busy}
                categories={scenario.decision_categories}
                evidence={discoveredEvidence}
                suggestions={state.suggestions}
                onAssess={controller.recordAssessment}
                onDecide={controller.recordDecision}
                onInvestigate={controller.requestWork}
                onMessage={controller.sendMessage}
                roles={state.roles}
              />
            </>
          )}
=======
          <Conversation
            activeThread={state.activeThread}
            events={state.events}
            evidence={discoveredEvidence}
            pendingMessage={state.pendingMessage}
            roles={state.roles}
            streamingRole={state.streamingRole}
            streamingText={state.streamingText}
          />
          <Composer
            activeThread={state.activeThread}
            busy={state.busy}
            categories={scenario.decision_categories}
            evidence={discoveredEvidence}
            suggestions={state.suggestions}
            onAssess={controller.recordAssessment}
            onDecide={controller.recordDecision}
            onInvestigate={controller.requestWork}
            onMessage={controller.sendMessage}
            roles={state.roles}
          />
>>>>>>> fork/updated_gamee_logic
        </main>
        <ContextRail
          assessments={state.assessments}
          busy={state.busy}
          evidence={discoveredEvidence}
          investigations={state.investigations}
          onShare={controller.shareEvidence}
          roles={state.roles}
        />
      </div>
    </div>
  );
}
