"use client";

import type { Scenario, Session } from "./types";

type Props = {
  scenario: Scenario;
  session: Session;
  busy: boolean;
  onAdvance: (minutes: number) => void;
  onEnd: () => void;
};

export default function TopBar({
  scenario,
  session,
  busy,
  onAdvance,
  onEnd,
}: Props) {
  const variant =
    scenario.variants.find((item) => item.id === session.variant_id)?.name ??
    session.variant_id;

  return (
    <header className="room-topbar">
      <div className="room-brand">
        Incident Room
        <small>{scenario.name} · {variant}</small>
      </div>
      <div className="room-clock">
        <em>T+</em> {String(session.simulation_time).padStart(3, "0")} <em>min</em>
      </div>
      <div className="room-advance" aria-label="Advance simulation time">
        <button disabled={busy} onClick={() => onAdvance(5)}>+5</button>
        <button disabled={busy} onClick={() => onAdvance(15)}>+15</button>
      </div>
      <div className="room-spacer" />
      <div className="trainee-identity">
        <span className="avatar trainee-avatar">TR</span>
        <span>
          <b>Exercise trainee</b>
          <small>External incident coordinator</small>
        </span>
      </div>
      <button className="room-end" disabled={busy} onClick={onEnd}>
        End exercise
      </button>
    </header>
  );
}
