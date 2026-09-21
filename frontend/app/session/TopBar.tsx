"use client";

import { useEffect, useState } from "react";

import type { Scenario, Session } from "./types";

type Props = {
  scenario: Scenario;
  session: Session;
  busy: boolean;
  onAdvance: (minutes: number) => void;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
};

export default function TopBar({
  scenario,
  session,
  busy,
  onAdvance,
  onPause,
  onResume,
  onEnd,
}: Props) {
  const variant =
    scenario.variants.find((item) => item.id === session.variant_id)?.name ??
    session.variant_id;
  const timeExpired =
    session.status === "completed" ||
    session.simulation_time >= scenario.duration_minutes;
  const [displaySeconds, setDisplaySeconds] = useState(
    session.simulation_time * 60 + Math.floor(session.clock_remainder_seconds),
  );

  useEffect(() => {
    const maximum = scenario.duration_minutes * 60;
    const base = Math.min(
      maximum,
      session.simulation_time * 60 + Math.floor(session.clock_remainder_seconds),
    );
    setDisplaySeconds(base);
    if (!session.clock_running || timeExpired) return;

    const anchoredAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - anchoredAt) / 1000);
      setDisplaySeconds(Math.min(maximum, base + elapsed));
    }, 250);
    return () => window.clearInterval(timer);
  }, [
    scenario.duration_minutes,
    session.clock_remainder_seconds,
    session.clock_running,
    session.simulation_time,
    timeExpired,
  ]);

  const displayMinutes = Math.floor(displaySeconds / 60);
  const displayRemainder = displaySeconds % 60;

  return (
    <header className="room-topbar">
      <div className="room-brand">
        Incident Room
        <small>{scenario.name} · {variant}</small>
      </div>
      <div className="room-clock">
        <em>T+</em> {String(displayMinutes).padStart(3, "0")}:
        {String(displayRemainder).padStart(2, "0")} <em>min:sec</em>
      </div>
      <div className="room-advance" aria-label="Advance simulation time">
        <button
          disabled={busy || timeExpired}
          onClick={session.clock_running ? onPause : onResume}
        >
          {session.clock_running ? "Pause" : "Resume"}
        </button>
        <button disabled={busy || timeExpired} onClick={() => onAdvance(5)}>+5</button>
        <button disabled={busy || timeExpired} onClick={() => onAdvance(15)}>+15</button>
        {timeExpired && (
          <span className="room-time-expired">
            Time limit reached — End exercise to see your result
          </span>
        )}
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
