"use client";

import type {
  AssessmentProjection,
  Evidence,
  InvestigationRun,
  Role,
} from "./types";
import { roleName } from "./ui";

type Props = {
  evidence: Evidence[];
  roles: Role[];
  investigations: InvestigationRun[];
  assessments: AssessmentProjection;
  busy: boolean;
  onShare: (fromRole: string, toRole: string, evidenceId: string) => Promise<boolean>;
};

export default function ContextRail({
  evidence,
  roles,
  investigations,
  assessments,
  busy,
  onShare,
}: Props) {
  const inFlight = investigations.filter((item) => item.status === "in_progress");

  return (
    <aside className="context-rail">
      <section>
        <h3>Discovered evidence</h3>
        <p className="context-caption">
          Exercise-wide view for the external trainee. Roles only use evidence they hold.
        </p>
        {evidence.length === 0 ? (
          <p className="context-empty">No evidence discovered yet.</p>
        ) : (
          <div className="context-list">
            {evidence.map((item) => {
              const holders = item.holders ?? [];
              const receivers = roles.filter((role) => !holders.includes(role.id));
              return (
                <article className="evidence-card" key={item.id}>
                  <div>
                    <b>{item.id}</b>
                    <span>{item.kind}</span>
                  </div>
                  <p>{item.statement}</p>
                  <small>
                    {item.reliability} · held by{" "}
                    {holders.map((id) => roleName(roles, id)).join(", ") || "no role"}
                  </small>
                  {holders.length > 0 && receivers.length > 0 && (
                    <label className="evidence-share">
                      Share with
                      <select
                        defaultValue=""
                        disabled={busy}
                        onChange={(event) => {
                          const to = event.target.value;
                          if (!to) return;
                          void onShare(holders[0], to, item.id);
                          event.target.value = "";
                        }}
                      >
                        <option value="" disabled>
                          Choose a role…
                        </option>
                        {receivers.map((role) => (
                          <option key={role.id} value={role.id}>
                            {role.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section>
        <h3>Work in flight</h3>
        <p className="context-caption">Investigations complete when simulation time advances.</p>
        {inFlight.length === 0 ? (
          <p className="context-empty">No active investigation.</p>
        ) : (
          <div className="context-list">
            {inFlight.map((item) => (
              <article className="work-card" key={item.id}>
                <b>{item.label}</b>
                <p>{item.request}</p>
                <small>
                  {roleName(roles, item.performer_role)} · due T+{item.due_at}
                </small>
                <div className="progress-track"><i /></div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3>Current assessments</h3>
        <p className="context-caption">Latest confidence recorded for each hypothesis.</p>
        {assessments.current.length === 0 ? (
          <p className="context-empty">No assessment logged.</p>
        ) : (
          <div className="context-list">
            {assessments.current.map((item) => (
              <article className="assessment-card" key={item.event_id}>
                <div>
                  <b>{item.hypothesis_label}</b>
                  <span>{item.confidence}</span>
                </div>
                <p>{item.statement}</p>
                <small>{roleName(roles, item.actor_role)} · T+{item.recorded_at}</small>
              </article>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
}
