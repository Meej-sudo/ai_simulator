"use client";

import { useState } from "react";

import type {
  Confidence,
  EventDefinition,
  InvestigationDefinition,
  RevealEffect,
  PersonalityProfile,
  ScenarioDocument,
  ScoringRule,
  ScoringRuleType,
  TriggerDefinition,
} from "./scenario-types";

type Props = {
  document: ScenarioDocument;
  onChange: (document: ScenarioDocument) => void;
};

type Section =
  | "scenario"
  | "roles"
  | "entities"
  | "evidence"
  | "hypotheses"
  | "investigations"
  | "timeline"
  | "variants"
  | "scoring";

const confidenceOptions: Confidence[] = ["low", "medium", "high", "confirmed"];
const scoringTypes: ScoringRuleType[] = [
  "role_contacted_within",
  "evidence_shared_within",
  "decision_within",
  "avoid_premature_assessment",
];

const personalityTraits: {
  id: keyof PersonalityProfile["traits"];
  label: string;
}[] = [
  { id: "openness", label: "Openness" },
  { id: "conscientiousness", label: "Conscientiousness" },
  { id: "extraversion", label: "Extraversion" },
  { id: "agreeableness", label: "Agreeableness" },
  { id: "emotional_stability", label: "Emotional stability" },
];

function defaultPersonality(): PersonalityProfile {
  return {
    summary: "Calm, professional, and focused on the role's responsibilities.",
    traits: {
      openness: "medium",
      conscientiousness: "medium",
      extraversion: "medium",
      agreeableness: "medium",
      emotional_stability: "medium",
    },
    behavioral_tendencies: [
      "Communicate clearly and identify what information is still needed.",
    ],
    under_pressure: "Remain professional and focus on the next useful action.",
  };
}

function replaceAt<T>(items: T[], index: number, item: T): T[] {
  return items.map((current, currentIndex) => currentIndex === index ? item : current);
}

function removeAt<T>(items: T[], index: number): T[] {
  return items.filter((_, currentIndex) => currentIndex !== index);
}

function nextId(prefix: string, existing: string[]): string {
  let number = 1;
  while (existing.includes(`${prefix}${String(number).padStart(3, "0")}`)) number += 1;
  return `${prefix}${String(number).padStart(3, "0")}`;
}

function nextKey(prefix: string, existing: string[]): string {
  let number = 1;
  while (existing.includes(`${prefix}_${number}`)) number += 1;
  return `${prefix}_${number}`;
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function scalar(value: string): unknown {
  if (value === "true") return true;
  if (value === "false") return false;
  if (value !== "" && Number.isFinite(Number(value))) return Number(value);
  return value;
}

function mapTrigger(
  trigger: TriggerDefinition,
  mapper: (trigger: TriggerDefinition) => TriggerDefinition,
): TriggerDefinition {
  const nested = trigger.type === "all" || trigger.type === "any"
    ? { ...trigger, triggers: trigger.triggers.map((item) => mapTrigger(item, mapper)) }
    : trigger;
  return mapper(nested);
}

function renameEvidenceReferences(
  document: ScenarioDocument,
  previous: string,
  next: string,
): ScenarioDocument {
  const rename = (value: string) => value === previous ? next : value;
  return {
    ...document,
    investigations: document.investigations.map((item) => ({
      ...item,
      prerequisites: {
        all_evidence: item.prerequisites.all_evidence.map(rename),
        any_evidence: item.prerequisites.any_evidence.map(rename),
      },
    })),
    events: document.events.map((item) => ({
      ...item,
      trigger: mapTrigger(item.trigger, (trigger) =>
        trigger.type === "evidence_known"
          ? { ...trigger, evidence_id: rename(trigger.evidence_id) }
          : trigger),
      ...(item.type === "reveal_evidence"
        ? {
            effects: item.effects.map((effect) => effect.type === "reveal_observation"
              ? { ...effect, observation_id: rename(effect.observation_id) }
              : { ...effect, finding_id: rename(effect.finding_id) }),
          }
        : item.type === "stakeholder_interaction" ? {
            follow_ups: item.follow_ups.map((followUp) => ({
              ...followUp,
              when: {
                ...followUp.when,
                evidence_support: {
                  ...followUp.when.evidence_support,
                  confirmation_evidence_ids: followUp.when.evidence_support.confirmation_evidence_ids.map(rename),
                },
              },
            })),
          }
        : {}),
    })) as EventDefinition[],
    variants: document.variants.map((variant) => ({
      ...variant,
      observation_overrides: variant.observation_overrides.map((item) => ({
        ...item,
        observation_id: rename(item.observation_id),
      })),
      timeline_overrides: variant.timeline_overrides.map((item) => ({
        ...item,
        observation_ids: item.observation_ids?.map(rename) ?? null,
      })),
      investigation_outcomes: variant.investigation_outcomes.map((item) => ({
        ...item,
        reveal_findings: item.reveal_findings.map(rename),
      })),
    })),
    scoring_rules: document.scoring_rules.map((item) => ({
      ...item,
      trigger_evidence: item.trigger_evidence === previous ? next : item.trigger_evidence,
      evidence_id: item.evidence_id === previous ? next : item.evidence_id,
      confirmation_evidence: item.confirmation_evidence === previous
        ? next
        : item.confirmation_evidence,
    })),
  };
}

function renameRoleReferences(
  document: ScenarioDocument,
  previous: string,
  next: string,
): ScenarioDocument {
  const rename = (value: string | null) => value === previous ? next : value;
  return {
    ...document,
    investigations: document.investigations.map((item) => ({
      ...item,
      performer_roles: item.performer_roles.map((id) => rename(id) ?? id),
    })),
    events: document.events.map((item) => ({
      ...item,
      trigger: mapTrigger(item.trigger, (trigger) => {
        if (trigger.type === "evidence_known") return { ...trigger, role_id: rename(trigger.role_id) ?? trigger.role_id };
        if (trigger.type === "assessment_exists" || trigger.type === "decision_recorded") return { ...trigger, actor_role: rename(trigger.actor_role) };
        if (trigger.type === "communication_sent") return { ...trigger, role_id: rename(trigger.role_id) };
        return trigger;
      }),
      ...(item.type === "reveal_evidence"
        ? { effects: item.effects.map((effect) => ({ ...effect, role_id: rename(effect.role_id) ?? effect.role_id })) }
        : item.type === "stakeholder_interaction"
          ? { actor_role: rename(item.actor_role) ?? item.actor_role }
          : item.source.kind === "role"
            ? { source: { ...item.source, id: rename(item.source.id) ?? item.source.id } }
            : {}),
    })) as EventDefinition[],
    variants: document.variants.map((variant) => ({
      ...variant,
      timeline_overrides: variant.timeline_overrides.map((item) => ({
        ...item,
        role: rename(item.role),
      })),
    })),
    scoring_rules: document.scoring_rules.map((item) => ({
      ...item,
      target_role: rename(item.target_role),
    })),
  };
}

function renameExternalEntityReferences(
  document: ScenarioDocument,
  previous: string,
  next: string,
): ScenarioDocument {
  return {
    ...document,
    events: document.events.map((item) => item.type === "organizational_pressure"
      && item.source.kind === "external_entity"
      && item.source.id === previous
      ? { ...item, source: { ...item.source, id: next } }
      : item) as EventDefinition[],
  };
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  wide = false,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: "text" | "number";
  wide?: boolean;
}) {
  return (
    <label className={wide ? "wide-field" : ""}>
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  help?: string;
}) {
  return (
    <label className="wide-field">
      {label}
      <textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)} />
      {help && <span className="field-help">{help}</span>}
    </label>
  );
}

function MultiSelect({
  label,
  options,
  selected,
  onChange,
  empty,
}: {
  label: string;
  options: { id: string; label: string }[];
  selected: string[];
  onChange: (selected: string[]) => void;
  empty: string;
}) {
  return (
    <div className="field-group wide-field">
      <span className="field-label">{label}</span>
      {options.length === 0 ? (
        <span className="field-help">{empty}</span>
      ) : (
        <div className="reference-list">
          {options.map((option) => (
            <label className="reference-option" key={option.id}>
              <input
                type="checkbox"
                checked={selected.includes(option.id)}
                onChange={(event) => {
                  onChange(
                    event.target.checked
                      ? [...selected, option.id]
                      : selected.filter((id) => id !== option.id),
                  );
                }}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function Heading({
  title,
  description,
  onAdd,
  addLabel,
}: {
  title: string;
  description: string;
  onAdd?: () => void;
  addLabel?: string;
}) {
  return (
    <div className="form-section-heading">
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      {onAdd && (
        <button type="button" className="small-button" onClick={onAdd}>
          {addLabel ?? "Add"}
        </button>
      )}
    </div>
  );
}

type SelectOption = { id: string; label: string };

type TriggerEditorProps = {
  trigger: TriggerDefinition;
  roles: SelectOption[];
  evidence: SelectOption[];
  hypotheses: SelectOption[];
  categories: SelectOption[];
  eventIds: SelectOption[];
  onChange: (trigger: TriggerDefinition) => void;
};

function newTrigger(type: TriggerDefinition["type"], props: TriggerEditorProps): TriggerDefinition {
  if (type === "simulation_time") return { type, at_minute: 0 };
  if (type === "assessment_exists") return {
    type,
    hypothesis_id: props.hypotheses[0]?.id ?? "",
    minimum_confidence: "medium",
    actor_role: null,
  };
  if (type === "evidence_known") return {
    type,
    role_id: props.roles[0]?.id ?? "",
    evidence_id: props.evidence[0]?.id ?? "",
  };
  if (type === "decision_recorded") return {
    type,
    decision_category: props.categories[0]?.id ?? "",
    actor_role: null,
    minimum_confidence: null,
  };
  if (type === "communication_sent") return {
    type,
    role_id: null,
    thread_id: "channel:bridge",
  };
  if (type === "event_fired") return {
    type,
    event_id: props.eventIds[0]?.id ?? "",
  };
  return { type, triggers: [{ type: "simulation_time", at_minute: 0 }] };
}

function TriggerEditor(props: TriggerEditorProps) {
  const { trigger, roles, evidence, hypotheses, categories, eventIds, onChange } = props;
  return (
    <div className="trigger-editor">
      <label>
        Trigger
        <select
          value={trigger.type}
          onChange={(event) => onChange(newTrigger(event.target.value as TriggerDefinition["type"], props))}
        >
          <option value="simulation_time">Simulation time</option>
          <option value="assessment_exists">Assessment exists</option>
          <option value="evidence_known">Evidence known</option>
          <option value="decision_recorded">Decision recorded</option>
          <option value="communication_sent">Communication sent</option>
          <option value="event_fired">Event fired</option>
          <option value="all">All conditions</option>
          <option value="any">Any condition</option>
        </select>
      </label>

      {trigger.type === "simulation_time" && (
        <Field label="Minute" type="number" value={trigger.at_minute} onChange={(value) => onChange({ ...trigger, at_minute: Math.max(0, Number(value)) })} />
      )}
      {trigger.type === "assessment_exists" && (
        <>
          <label>Hypothesis<select value={trigger.hypothesis_id} onChange={(event) => onChange({ ...trigger, hypothesis_id: event.target.value })}>{hypotheses.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Minimum confidence<select value={trigger.minimum_confidence} onChange={(event) => onChange({ ...trigger, minimum_confidence: event.target.value as Confidence })}>{confidenceOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label>Acting role (optional)<select value={trigger.actor_role ?? ""} onChange={(event) => onChange({ ...trigger, actor_role: event.target.value || null })}><option value="">Any role</option>{roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        </>
      )}
      {trigger.type === "evidence_known" && (
        <>
          <label>Role that knows it<select value={trigger.role_id} onChange={(event) => onChange({ ...trigger, role_id: event.target.value })}>{roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Evidence<select value={trigger.evidence_id} onChange={(event) => onChange({ ...trigger, evidence_id: event.target.value })}>{evidence.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        </>
      )}
      {trigger.type === "decision_recorded" && (
        <>
          <label>Decision category<select value={trigger.decision_category} onChange={(event) => onChange({ ...trigger, decision_category: event.target.value })}>{categories.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Acting role (optional)<select value={trigger.actor_role ?? ""} onChange={(event) => onChange({ ...trigger, actor_role: event.target.value || null })}><option value="">Any role</option>{roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Minimum confidence (optional)<select value={trigger.minimum_confidence ?? ""} onChange={(event) => onChange({ ...trigger, minimum_confidence: (event.target.value || null) as Confidence | null })}><option value="">Not required</option>{confidenceOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        </>
      )}
      {trigger.type === "communication_sent" && (
        <>
          <label>Related role (optional)<select value={trigger.role_id ?? ""} onChange={(event) => onChange({ ...trigger, role_id: event.target.value || null })}><option value="">Any role</option>{roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <Field label="Thread ID (optional)" value={trigger.thread_id ?? ""} onChange={(value) => onChange({ ...trigger, thread_id: value || null })} />
        </>
      )}
      {trigger.type === "event_fired" && (
        <label>Authored event<select value={trigger.event_id} onChange={(event) => onChange({ ...trigger, event_id: event.target.value })}>{eventIds.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      )}
      {(trigger.type === "all" || trigger.type === "any") && (
        <div className="trigger-children wide-field">
          <div className="nested-heading"><span>{trigger.type === "all" ? "Every condition must match" : "At least one condition must match"}</span><button type="button" className="small-button" onClick={() => onChange({ ...trigger, triggers: [...trigger.triggers, { type: "simulation_time", at_minute: 0 }] })}>Add condition</button></div>
          {trigger.triggers.map((child, index) => (
            <div className="trigger-child" key={index}>
              <TriggerEditor {...props} trigger={child} onChange={(next) => onChange({ ...trigger, triggers: replaceAt(trigger.triggers, index, next) })} />
              {trigger.triggers.length > 1 && <button type="button" className="danger-button" onClick={() => onChange({ ...trigger, triggers: removeAt(trigger.triggers, index) })}>Remove condition</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ScenarioForm({ document, onChange }: Props) {
  const [section, setSection] = useState<Section>("scenario");
  const roles = document.roles.map((item) => ({ id: item.id, label: item.display_name }));
  const externalEntities = document.external_entities.map((item) => ({
    id: item.id,
    label: item.display_name,
  }));
  const observations = document.observations.map((item) => ({
    id: item.id,
    label: `${item.id} - ${item.statement}`,
  }));
  const findings = document.findings.map((item) => ({
    id: item.id,
    label: `${item.id} - ${item.statement}`,
  }));
  const evidence = [...observations, ...findings];
  const hypotheses = document.hypotheses.map((item) => ({
    id: item.id,
    label: `${item.id} - ${item.label}`,
  }));
  const categories = document.scenario.decision_categories.map((item) => ({
    id: item.id,
    label: item.display_name,
  }));
  const tabs: { id: Section; label: string; count?: number }[] = [
    { id: "scenario", label: "Scenario" },
    { id: "roles", label: "Roles", count: document.roles.length },
    { id: "entities", label: "External", count: document.external_entities.length },
    { id: "evidence", label: "Evidence", count: evidence.length },
    { id: "hypotheses", label: "Hypotheses", count: hypotheses.length },
    { id: "investigations", label: "Investigations", count: document.investigations.length },
    { id: "timeline", label: "Events", count: document.events.length },
    { id: "variants", label: "Variants", count: document.variants.length },
    { id: "scoring", label: "Scoring", count: document.scoring_rules.length },
  ];

  function updateInvestigation(index: number, next: InvestigationDefinition) {
    onChange({ ...document, investigations: replaceAt(document.investigations, index, next) });
  }

  function updateScoring(index: number, next: ScoringRule) {
    onChange({ ...document, scoring_rules: replaceAt(document.scoring_rules, index, next) });
  }

  return (
    <div className="scenario-form">
      <nav className="form-tabs" aria-label="Scenario form sections">
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab.id}
            className={section === tab.id ? "active" : ""}
            onClick={() => setSection(tab.id)}
          >
            {tab.label}{tab.count !== undefined && <span>{tab.count}</span>}
          </button>
        ))}
      </nav>

      {section === "scenario" && (
        <section className="form-section">
          <Heading
            title="Scenario overview"
            description="Core exercise metadata and broad decision categories."
          />
          <div className="form-card">
            <div className="form-grid">
              <Field label="Stable ID" value={document.scenario.id} onChange={() => undefined} />
              <Field
                label="Duration (minutes)"
                type="number"
                value={document.scenario.duration_minutes}
                onChange={(value) => onChange({
                  ...document,
                  scenario: { ...document.scenario, duration_minutes: Math.max(1, Number(value)) },
                })}
              />
              <Field
                label="Name"
                wide
                value={document.scenario.name}
                onChange={(value) => onChange({
                  ...document,
                  scenario: { ...document.scenario, name: value },
                })}
              />
              <TextField
                label="Description"
                value={document.scenario.description}
                onChange={(value) => onChange({
                  ...document,
                  scenario: { ...document.scenario, description: value },
                })}
              />
            </div>
          </div>
          <Heading
            title="Decision categories"
            description="Categories reveal less than suggested decisions; trainees enter the decision itself."
            addLabel="Add category"
            onAdd={() => onChange({
              ...document,
              scenario: {
                ...document.scenario,
                decision_categories: [
                  ...document.scenario.decision_categories,
                  {
                    id: nextKey("category", categories.map((item) => item.id)),
                    display_name: "New category",
                    description: "",
                    captures_confidence: false,
                  },
                ],
              },
            })}
          />
          <div className="form-card-list">
            {document.scenario.decision_categories.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.display_name || "Unnamed category"}</strong>
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => onChange({
                      ...document,
                      scenario: {
                        ...document.scenario,
                        decision_categories: removeAt(
                          document.scenario.decision_categories,
                          index,
                        ),
                      },
                    })}
                  >
                    Remove
                  </button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange({
                    ...document,
                    scenario: {
                      ...document.scenario,
                      decision_categories: replaceAt(
                        document.scenario.decision_categories,
                        index,
                        { ...item, id: value },
                      ),
                    },
                    scoring_rules: document.scoring_rules.map((rule) => ({
                      ...rule,
                      decision_category: rule.decision_category === item.id
                        ? value
                        : rule.decision_category,
                    })),
                    events: document.events.map((authoredEvent) => ({
                      ...authoredEvent,
                      trigger: mapTrigger(authoredEvent.trigger, (trigger) =>
                        trigger.type === "decision_recorded" && trigger.decision_category === item.id
                          ? { ...trigger, decision_category: value }
                          : trigger),
                    })) as EventDefinition[],
                  })} />
                  <Field label="Display name" value={item.display_name} onChange={(value) => onChange({
                    ...document,
                    scenario: {
                      ...document.scenario,
                      decision_categories: replaceAt(
                        document.scenario.decision_categories,
                        index,
                        { ...item, display_name: value },
                      ),
                    },
                  })} />
                  <TextField label="Description" value={item.description} onChange={(value) => onChange({
                    ...document,
                    scenario: {
                      ...document.scenario,
                      decision_categories: replaceAt(
                        document.scenario.decision_categories,
                        index,
                        { ...item, description: value },
                      ),
                    },
                  })} />
                  <label className="check-field">
                    <input
                      type="checkbox"
                      checked={item.captures_confidence}
                      onChange={(event) => onChange({
                        ...document,
                        scenario: {
                          ...document.scenario,
                          decision_categories: replaceAt(
                            document.scenario.decision_categories,
                            index,
                            { ...item, captures_confidence: event.target.checked },
                          ),
                        },
                      })}
                    />
                    Ask for confidence
                  </label>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "roles" && (
        <section className="form-section">
          <Heading
            title="Participant roles"
            description="Roles are stored in the shared catalog. Edits affect every scenario that references a role; removing one here only removes it from this scenario."
            addLabel="Add role"
            onAdd={() => onChange({
              ...document,
              roles: [
                ...document.roles,
                {
                  id: nextKey("role", document.roles.map((item) => item.id)),
                  display_name: "New role",
                  responsibilities: ["Describe this role's responsibility"],
                  communication_style: { tone: "professional", verbosity: "medium" },
                  personality: defaultPersonality(),
                  response_guidance: null,
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.roles.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.display_name}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    roles: removeAt(document.roles, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange(renameRoleReferences({
                    ...document,
                    roles: replaceAt(document.roles, index, { ...item, id: value }),
                  }, item.id, value))} />
                  <Field label="Display name" value={item.display_name} onChange={(value) => onChange({
                    ...document,
                    roles: replaceAt(document.roles, index, { ...item, display_name: value }),
                  })} />
                  <TextField
                    label="Responsibilities (one per line)"
                    value={item.responsibilities.join("\n")}
                    onChange={(value) => onChange({
                      ...document,
                      roles: replaceAt(document.roles, index, {
                        ...item,
                        responsibilities: lines(value),
                      }),
                    })}
                  />
                  <Field label="Tone" value={item.communication_style.tone} onChange={(value) => onChange({
                    ...document,
                    roles: replaceAt(document.roles, index, {
                      ...item,
                      communication_style: { ...item.communication_style, tone: value },
                    }),
                  })} />
                  <label>
                    Verbosity
                    <select
                      value={item.communication_style.verbosity}
                      onChange={(event) => onChange({
                        ...document,
                        roles: replaceAt(document.roles, index, {
                          ...item,
                          communication_style: {
                            ...item.communication_style,
                            verbosity: event.target.value as "low" | "medium" | "high",
                          },
                        }),
                      })}
                    >
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                    </select>
                  </label>
                  <TextField
                    label="Personality summary"
                    value={item.personality.summary}
                    onChange={(value) => onChange({
                      ...document,
                      roles: replaceAt(document.roles, index, {
                        ...item,
                        personality: { ...item.personality, summary: value },
                      }),
                    })}
                  />
                  {personalityTraits.map((trait) => (
                    <label key={trait.id}>
                      {trait.label}
                      <select
                        value={item.personality.traits[trait.id]}
                        onChange={(event) => onChange({
                          ...document,
                          roles: replaceAt(document.roles, index, {
                            ...item,
                            personality: {
                              ...item.personality,
                              traits: {
                                ...item.personality.traits,
                                [trait.id]: event.target.value as "low" | "medium" | "high",
                              },
                            },
                          }),
                        })}
                      >
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                      </select>
                    </label>
                  ))}
                  <TextField
                    label="Behavioral tendencies (one per line)"
                    value={item.personality.behavioral_tendencies.join("\n")}
                    onChange={(value) => onChange({
                      ...document,
                      roles: replaceAt(document.roles, index, {
                        ...item,
                        personality: {
                          ...item.personality,
                          behavioral_tendencies: lines(value),
                        },
                      }),
                    })}
                  />
                  <TextField
                    label="Behavior under pressure"
                    value={item.personality.under_pressure}
                    onChange={(value) => onChange({
                      ...document,
                      roles: replaceAt(document.roles, index, {
                        ...item,
                        personality: { ...item.personality, under_pressure: value },
                      }),
                    })}
                  />
                  <TextField
                    label="Response guidance"
                    value={item.response_guidance ?? ""}
                    onChange={(value) => onChange({
                      ...document,
                      roles: replaceAt(document.roles, index, {
                        ...item,
                        response_guidance: value || null,
                      }),
                    })}
                  />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "entities" && (
        <section className="form-section">
          <Heading
            title="External entities"
            description="Authorities, law enforcement, media, and other communication recipients."
            addLabel="Add entity"
            onAdd={() => onChange({
              ...document,
              external_entities: [
                ...document.external_entities,
                {
                  id: nextKey("entity", document.external_entities.map((item) => item.id)),
                  display_name: "New external entity",
                  type: "organization",
                  accepts: ["incident_report"],
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.external_entities.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.display_name}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    external_entities: removeAt(document.external_entities, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange(
                    renameExternalEntityReferences({
                      ...document,
                      external_entities: replaceAt(document.external_entities, index, { ...item, id: value }),
                    }, item.id, value),
                  )} />
                  <Field label="Display name" value={item.display_name} onChange={(value) => onChange({
                    ...document,
                    external_entities: replaceAt(document.external_entities, index, { ...item, display_name: value }),
                  })} />
                  <Field label="Type" value={item.type} onChange={(value) => onChange({
                    ...document,
                    external_entities: replaceAt(document.external_entities, index, { ...item, type: value }),
                  })} />
                  <TextField label="Accepted communication types (one per line)" value={item.accepts.join("\n")} onChange={(value) => onChange({
                    ...document,
                    external_entities: replaceAt(document.external_entities, index, { ...item, accepts: lines(value) }),
                  })} />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "evidence" && (
        <section className="form-section">
          <Heading
            title="Observations"
            description="Ambiguous signals granted by scenario events. They should not state the hidden answer."
            addLabel="Add observation"
            onAdd={() => onChange({
              ...document,
              observations: [
                ...document.observations,
                {
                  id: nextId("O", document.observations.map((item) => item.id)),
                  source: "monitoring",
                  statement: "Describe an observable signal.",
                  reliability: "medium",
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.observations.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.id}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    observations: removeAt(document.observations, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange(renameEvidenceReferences({
                    ...document,
                    observations: replaceAt(document.observations, index, { ...item, id: value }),
                  }, item.id, value))} />
                  <Field label="Source" value={item.source} onChange={(value) => onChange({
                    ...document,
                    observations: replaceAt(document.observations, index, { ...item, source: value }),
                  })} />
                  <TextField label="Statement" value={item.statement} onChange={(value) => onChange({
                    ...document,
                    observations: replaceAt(document.observations, index, { ...item, statement: value }),
                  })} />
                  <label>
                    Reliability
                    <select value={item.reliability} onChange={(event) => onChange({
                      ...document,
                      observations: replaceAt(document.observations, index, {
                        ...item,
                        reliability: event.target.value as Confidence,
                      }),
                    })}>
                      {confidenceOptions.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                </div>
              </article>
            ))}
          </div>

          <Heading
            title="Findings"
            description="Evidence revealed only when a matching investigation completes."
            addLabel="Add finding"
            onAdd={() => onChange({
              ...document,
              findings: [
                ...document.findings,
                {
                  id: nextId("FD", document.findings.map((item) => item.id)),
                  statement: "Describe an investigation result.",
                  reliability: "high",
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.findings.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.id}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    findings: removeAt(document.findings, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange(renameEvidenceReferences({
                    ...document,
                    findings: replaceAt(document.findings, index, { ...item, id: value }),
                  }, item.id, value))} />
                  <label>
                    Reliability
                    <select value={item.reliability} onChange={(event) => onChange({
                      ...document,
                      findings: replaceAt(document.findings, index, {
                        ...item,
                        reliability: event.target.value as Confidence,
                      }),
                    })}>
                      {confidenceOptions.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                  <TextField label="Statement" value={item.statement} onChange={(value) => onChange({
                    ...document,
                    findings: replaceAt(document.findings, index, { ...item, statement: value }),
                  })} />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "hypotheses" && (
        <section className="form-section">
          <Heading
            title="Public hypotheses"
            description="Named propositions trainees can assess. These labels do not expose variant truth."
            addLabel="Add hypothesis"
            onAdd={() => onChange({
              ...document,
              hypotheses: [
                ...document.hypotheses,
                {
                  id: nextId("H", document.hypotheses.map((item) => item.id)),
                  key: nextKey("hypothesis", document.hypotheses.map((item) => item.key)),
                  label: "New hypothesis",
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.hypotheses.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.label}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    hypotheses: removeAt(document.hypotheses, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => onChange({
                    ...document,
                    hypotheses: replaceAt(document.hypotheses, index, { ...item, id: value }),
                    scoring_rules: document.scoring_rules.map((rule) => ({
                      ...rule,
                      hypothesis_id: rule.hypothesis_id === item.id ? value : rule.hypothesis_id,
                    })),
                    events: document.events.map((authoredEvent) => ({
                      ...authoredEvent,
                      trigger: mapTrigger(authoredEvent.trigger, (trigger) =>
                        trigger.type === "assessment_exists" && trigger.hypothesis_id === item.id
                          ? { ...trigger, hypothesis_id: value }
                          : trigger),
                      ...(authoredEvent.type === "stakeholder_interaction"
                        ? {
                            follow_ups: authoredEvent.follow_ups.map((followUp) => ({
                              ...followUp,
                              when: {
                                ...followUp.when,
                                trainee_assessment: {
                                  ...followUp.when.trainee_assessment,
                                  hypothesis_id: followUp.when.trainee_assessment.hypothesis_id === item.id
                                    ? value
                                    : followUp.when.trainee_assessment.hypothesis_id,
                                },
                              },
                            })),
                          }
                        : {}),
                    })) as EventDefinition[],
                  })} />
                  <Field label="Key" value={item.key} onChange={(value) => onChange({
                    ...document,
                    hypotheses: replaceAt(document.hypotheses, index, { ...item, key: value }),
                  })} />
                  <Field label="Trainee-facing label" wide value={item.label} onChange={(value) => onChange({
                    ...document,
                    hypotheses: replaceAt(document.hypotheses, index, { ...item, label: value }),
                  })} />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "investigations" && (
        <section className="form-section">
          <Heading
            title="Investigation catalog"
            description="The trainee writes a request; the LLM routes it among only currently eligible public definitions."
            addLabel="Add investigation"
            onAdd={() => {
              if (!document.roles[0] || !document.findings[0]) return;
              const investigation: InvestigationDefinition = {
                id: nextId("I", document.investigations.map((item) => item.id)),
                label: "New investigation",
                performer_roles: [document.roles[0].id],
                request_description: "Describe what this investigation determines.",
                match_hints: ["example trainee phrasing"],
                prerequisites: { all_evidence: [], any_evidence: [] },
                duration_minutes: 5,
                repeatable: false,
              };
              onChange({
                ...document,
                investigations: [...document.investigations, investigation],
                variants: document.variants.map((variant) => ({
                  ...variant,
                  investigation_outcomes: [
                    ...variant.investigation_outcomes,
                    {
                      investigation_id: investigation.id,
                      reveal_findings: [document.findings[0].id],
                    },
                  ],
                })),
              });
            }}
          />
          {!document.findings[0] && (
            <p className="editor-warning">Create at least one finding before adding an investigation.</p>
          )}
          <div className="form-card-list">
            {document.investigations.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.id} - {item.label}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    investigations: removeAt(document.investigations, index),
                    variants: document.variants.map((variant) => ({
                      ...variant,
                      investigation_outcomes: variant.investigation_outcomes.filter(
                        (outcome) => outcome.investigation_id !== item.id,
                      ),
                    })),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => {
                    onChange({
                      ...document,
                      investigations: replaceAt(document.investigations, index, {
                        ...item,
                        id: value,
                      }),
                      variants: document.variants.map((variant) => ({
                        ...variant,
                        investigation_outcomes: variant.investigation_outcomes.map((outcome) => ({
                          ...outcome,
                          investigation_id: outcome.investigation_id === item.id
                            ? value
                            : outcome.investigation_id,
                        })),
                      })),
                    });
                  }} />
                  <Field label="Label" value={item.label} onChange={(value) => updateInvestigation(index, { ...item, label: value })} />
                  <Field
                    label="Duration (minutes)"
                    type="number"
                    value={item.duration_minutes}
                    onChange={(value) => updateInvestigation(index, {
                      ...item,
                      duration_minutes: Math.max(0, Number(value)),
                    })}
                  />
                  <label className="check-field">
                    <input
                      type="checkbox"
                      checked={item.repeatable}
                      onChange={(event) => updateInvestigation(index, {
                        ...item,
                        repeatable: event.target.checked,
                      })}
                    />
                    Repeatable
                  </label>
                  <TextField
                    label="Public request description"
                    value={item.request_description}
                    onChange={(value) => updateInvestigation(index, {
                      ...item,
                      request_description: value,
                    })}
                  />
                  <TextField
                    label="Example matching phrases (one per line)"
                    value={item.match_hints.join("\n")}
                    onChange={(value) => updateInvestigation(index, {
                      ...item,
                      match_hints: lines(value),
                    })}
                    help="Use natural phrases a trainee might type; do not include the finding or answer."
                  />
                  <MultiSelect
                    label="Performer roles"
                    options={roles}
                    selected={item.performer_roles}
                    onChange={(selected) => updateInvestigation(index, {
                      ...item,
                      performer_roles: selected,
                    })}
                    empty="Create roles first."
                  />
                  <MultiSelect
                    label="Required evidence (all)"
                    options={evidence}
                    selected={item.prerequisites.all_evidence}
                    onChange={(selected) => updateInvestigation(index, {
                      ...item,
                      prerequisites: { ...item.prerequisites, all_evidence: selected },
                    })}
                    empty="Create evidence first."
                  />
                  <MultiSelect
                    label="Required evidence (at least one)"
                    options={evidence}
                    selected={item.prerequisites.any_evidence}
                    onChange={(selected) => updateInvestigation(index, {
                      ...item,
                      prerequisites: { ...item.prerequisites, any_evidence: selected },
                    })}
                    empty="Create evidence first."
                  />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "timeline" && (
        <section className="form-section">
          <Heading
            title="Authored events"
            description="Define deterministic triggers. Reveal events change knowledge, pressure events publish passive demands, and stakeholder events ask the trainee for a response. The model only writes stakeholder wording."
            addLabel="Add event"
            onAdd={() => {
              if (!document.roles[0] || !document.observations[0]) return;
              onChange({
                ...document,
                events: [
                  ...document.events,
                  {
                    id: nextId("E", document.events.map((item) => item.id)),
                    type: "reveal_evidence",
                    trigger: { type: "simulation_time", at_minute: 0 },
                    effects: [{
                      type: "reveal_observation",
                      role_id: document.roles[0].id,
                      observation_id: document.observations[0].id,
                    }],
                    once: true,
                  },
                ],
              });
            }}
          />
          <div className="form-card-list">
            {document.events.map((item, index) => {
              const updateEvent = (next: EventDefinition) => onChange({
                ...document,
                events: replaceAt(document.events, index, next),
              });
              const eventIds = document.events
                .filter((candidate) => candidate.id !== item.id)
                .map((candidate) => ({ id: candidate.id, label: candidate.id }));
              return (
                <article className="form-card event-card" key={`${item.id}-${index}`}>
                  <div className="form-card-heading">
                    <strong>{item.id} · {item.type === "reveal_evidence"
                      ? "Reveal evidence"
                      : item.type === "organizational_pressure"
                        ? "Organizational pressure"
                        : "Stakeholder interaction"}</strong>
                    <button type="button" className="danger-button" onClick={() => onChange({
                      ...document,
                      events: removeAt(document.events, index),
                    })}>Remove</button>
                  </div>
                  <div className="form-grid">
                    <Field label="ID" value={item.id} onChange={(value) => onChange({
                      ...document,
                      events: document.events.map((candidate, candidateIndex) => ({
                        ...candidate,
                        id: candidateIndex === index ? value : candidate.id,
                        trigger: mapTrigger(candidate.trigger, (trigger) =>
                          trigger.type === "event_fired" && trigger.event_id === item.id
                            ? { ...trigger, event_id: value }
                            : trigger),
                      })) as EventDefinition[],
                      variants: document.variants.map((variant) => ({
                        ...variant,
                        timeline_overrides: variant.timeline_overrides.map((override) => ({
                          ...override,
                          event_id: override.event_id === item.id ? value : override.event_id,
                        })),
                      })),
                    })} />
                    <label>
                      Event kind
                      <select value={item.type} onChange={(event) => {
                        if (event.target.value === item.type) return;
                        if (event.target.value === "stakeholder_interaction") {
                          updateEvent({
                            id: item.id,
                            type: "stakeholder_interaction",
                            trigger: item.trigger,
                            actor_role: document.roles[0]?.id ?? "",
                            interaction: { objective: "Request an incident update.", context: [] },
                            follow_ups: [],
                            once: item.once,
                          });
                        } else if (event.target.value === "organizational_pressure") {
                          const role = document.roles[0];
                          updateEvent({
                            id: item.id,
                            type: "organizational_pressure",
                            trigger: item.trigger,
                            source: role
                              ? { kind: "role", id: role.id }
                              : { kind: "external_entity", id: document.external_entities[0]?.id ?? "" },
                            pressure: {
                              category: "operational",
                              severity: "medium",
                              message: "Describe the pressure placed on the incident team.",
                            },
                            once: item.once,
                          });
                        } else {
                          updateEvent({
                            id: item.id,
                            type: "reveal_evidence",
                            trigger: item.trigger,
                            effects: [{
                              type: "reveal_observation",
                              role_id: document.roles[0]?.id ?? "",
                              observation_id: document.observations[0]?.id ?? "",
                            }],
                            once: item.once,
                          });
                        }
                      }}>
                        <option value="reveal_evidence">Reveal evidence</option>
                        <option value="organizational_pressure">Organizational pressure</option>
                        <option value="stakeholder_interaction">Stakeholder interaction</option>
                      </select>
                    </label>
                    <label className="check-field">
                      <input type="checkbox" checked={item.once} onChange={(event) => updateEvent({ ...item, once: event.target.checked })} />
                      Fire only once
                    </label>
                    <div className="wide-field">
                      <TriggerEditor
                        trigger={item.trigger}
                        roles={roles}
                        evidence={evidence}
                        hypotheses={hypotheses}
                        categories={categories}
                        eventIds={eventIds}
                        onChange={(trigger) => updateEvent({ ...item, trigger })}
                      />
                    </div>

                    {item.type === "reveal_evidence" ? (
                      <div className="wide-field nested-editor">
                        <div className="nested-heading">
                          <span>Knowledge effects</span>
                          <button type="button" className="small-button" disabled={!document.roles[0] || !document.observations[0]} onClick={() => updateEvent({
                            ...item,
                            effects: [...item.effects, {
                              type: "reveal_observation",
                              role_id: document.roles[0]?.id ?? "",
                              observation_id: document.observations[0]?.id ?? "",
                            }],
                          })}>Add effect</button>
                        </div>
                        {item.effects.map((effect, effectIndex) => (
                          <div className="effect-row" key={effectIndex}>
                            <label>Effect<select value={effect.type} onChange={(event) => {
                              const next: RevealEffect = event.target.value === "reveal_finding"
                                ? { type: "reveal_finding", role_id: effect.role_id, finding_id: document.findings[0]?.id ?? "" }
                                : { type: "reveal_observation", role_id: effect.role_id, observation_id: document.observations[0]?.id ?? "" };
                              updateEvent({ ...item, effects: replaceAt(item.effects, effectIndex, next) });
                            }}><option value="reveal_observation">Reveal observation</option><option value="reveal_finding">Reveal finding</option></select></label>
                            <label>Recipient role<select value={effect.role_id} onChange={(event) => updateEvent({ ...item, effects: replaceAt(item.effects, effectIndex, { ...effect, role_id: event.target.value }) })}>{roles.map((role) => <option key={role.id} value={role.id}>{role.label}</option>)}</select></label>
                            <label>Evidence<select value={effect.type === "reveal_observation" ? effect.observation_id : effect.finding_id} onChange={(event) => {
                              const next: RevealEffect = effect.type === "reveal_observation"
                                ? { ...effect, observation_id: event.target.value }
                                : { ...effect, finding_id: event.target.value };
                              updateEvent({ ...item, effects: replaceAt(item.effects, effectIndex, next) });
                            }}>{(effect.type === "reveal_observation" ? observations : findings).map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
                            {item.effects.length > 1 && <button type="button" className="danger-button" onClick={() => updateEvent({ ...item, effects: removeAt(item.effects, effectIndex) })}>Remove</button>}
                          </div>
                        ))}
                      </div>
                    ) : item.type === "organizational_pressure" ? (
                      <>
                        <label>
                          Source kind
                          <select value={item.source.kind} onChange={(event) => {
                            const kind = event.target.value as "role" | "external_entity";
                            updateEvent({
                              ...item,
                              source: {
                                kind,
                                id: kind === "role"
                                  ? document.roles[0]?.id ?? ""
                                  : document.external_entities[0]?.id ?? "",
                              },
                            });
                          }}>
                            <option value="role">Internal role</option>
                            <option value="external_entity">External entity</option>
                          </select>
                        </label>
                        <label>
                          Source
                          <select value={item.source.id} onChange={(event) => updateEvent({
                            ...item,
                            source: { ...item.source, id: event.target.value },
                          })}>
                            {(item.source.kind === "role" ? roles : externalEntities).map((option) => (
                              <option key={option.id} value={option.id}>{option.label}</option>
                            ))}
                          </select>
                        </label>
                        <Field label="Pressure category" value={item.pressure.category} onChange={(value) => updateEvent({
                          ...item,
                          pressure: { ...item.pressure, category: value },
                        })} />
                        <label>
                          Severity
                          <select value={item.pressure.severity} onChange={(event) => updateEvent({
                            ...item,
                            pressure: {
                              ...item.pressure,
                              severity: event.target.value as typeof item.pressure.severity,
                            },
                          })}>
                            <option value="low">low</option>
                            <option value="medium">medium</option>
                            <option value="high">high</option>
                            <option value="critical">critical</option>
                          </select>
                        </label>
                        <TextField label="Pressure message" value={item.pressure.message} onChange={(value) => updateEvent({
                          ...item,
                          pressure: { ...item.pressure, message: value },
                        })} help="Shown verbatim in the incident bridge; no LLM call or chat thread is created." />
                      </>
                    ) : (
                      <>
                        <label>Stakeholder<select value={item.actor_role} onChange={(event) => updateEvent({ ...item, actor_role: event.target.value })}>{roles.map((role) => <option key={role.id} value={role.id}>{role.label}</option>)}</select></label>
                        <TextField label="Interaction objective" value={item.interaction.objective} onChange={(value) => updateEvent({ ...item, interaction: { ...item.interaction, objective: value } })} help="Describe what the stakeholder needs. The model turns this into natural language." />
                        <TextField label="Context (one instruction per line)" value={item.interaction.context.join("\n")} onChange={(value) => updateEvent({ ...item, interaction: { ...item.interaction, context: lines(value) } })} />
                        <div className="wide-field nested-editor">
                          <div className="nested-heading">
                            <span>Deterministic follow-ups</span>
                            <button type="button" className="small-button" disabled={!document.hypotheses[0] || evidence.length === 0} onClick={() => updateEvent({
                              ...item,
                              follow_ups: [...item.follow_ups, {
                                id: nextId("FU", item.follow_ups.map((followUp) => followUp.id)),
                                when: {
                                  trainee_assessment: { hypothesis_id: document.hypotheses[0]?.id ?? "", confidence: "confirmed" },
                                  evidence_support: { below: "confirmed", confirmation_evidence_ids: [evidence[0]?.id ?? ""] },
                                },
                                objective: "Ask what evidence supports the trainee's statement.",
                                context: [],
                              }],
                            })}>Add follow-up</button>
                          </div>
                          {item.follow_ups.length === 0 && <p className="editor-caption">No follow-up. The first trainee response will resolve this request.</p>}
                          {item.follow_ups.map((followUp, followUpIndex) => {
                            const updateFollowUp = (next: typeof followUp) => updateEvent({ ...item, follow_ups: replaceAt(item.follow_ups, followUpIndex, next) });
                            return (
                              <div className="follow-up-editor" key={`${followUp.id}-${followUpIndex}`}>
                                <Field label="Follow-up ID" value={followUp.id} onChange={(value) => updateFollowUp({ ...followUp, id: value })} />
                                <label>Claimed hypothesis<select value={followUp.when.trainee_assessment.hypothesis_id} onChange={(event) => updateFollowUp({ ...followUp, when: { ...followUp.when, trainee_assessment: { ...followUp.when.trainee_assessment, hypothesis_id: event.target.value } } })}>{hypotheses.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
                                <label>Claimed confidence<select value={followUp.when.trainee_assessment.confidence} onChange={(event) => updateFollowUp({ ...followUp, when: { ...followUp.when, trainee_assessment: { ...followUp.when.trainee_assessment, confidence: event.target.value as Confidence } } })}>{confidenceOptions.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
                                <label>Evidence support below<select value={followUp.when.evidence_support.below} onChange={(event) => updateFollowUp({ ...followUp, when: { ...followUp.when, evidence_support: { ...followUp.when.evidence_support, below: event.target.value as Confidence } } })}>{confidenceOptions.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
                                <MultiSelect label="Confirmation evidence" options={evidence} selected={followUp.when.evidence_support.confirmation_evidence_ids} onChange={(selected) => updateFollowUp({ ...followUp, when: { ...followUp.when, evidence_support: { ...followUp.when.evidence_support, confirmation_evidence_ids: selected } } })} empty="Create evidence first." />
                                <TextField label="Follow-up objective" value={followUp.objective} onChange={(value) => updateFollowUp({ ...followUp, objective: value })} />
                                <TextField label="Follow-up context (one instruction per line)" value={followUp.context.join("\n")} onChange={(value) => updateFollowUp({ ...followUp, context: lines(value) })} />
                                <button type="button" className="danger-button" onClick={() => updateEvent({ ...item, follow_ups: removeAt(item.follow_ups, followUpIndex) })}>Remove follow-up</button>
                              </div>
                            );
                          })}
                        </div>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {section === "variants" && (
        <section className="form-section">
          <Heading
            title="Variant outcomes"
            description="Keep truth hidden. Map every investigation to deterministic findings for each variant."
            addLabel="Add variant"
            onAdd={() => {
              if (!document.findings[0]) return;
              const id = nextKey("variant", document.variants.map((item) => item.id));
              onChange({
                ...document,
                variants: [
                  ...document.variants,
                  {
                    id,
                    name: "New variant",
                    ground_truth: {},
                    observation_overrides: [],
                    timeline_overrides: [],
                    investigation_outcomes: document.investigations.map((item) => ({
                      investigation_id: item.id,
                      reveal_findings: [document.findings[0].id],
                    })),
                  },
                ],
              });
            }}
          />
          {!document.findings[0] && (
            <p className="editor-warning">Create at least one finding before adding a variant.</p>
          )}
          <div className="form-card-list">
            {document.variants.map((variant, variantIndex) => (
              <article className="form-card variant-card" key={variant.id}>
                <div className="form-card-heading">
                  <strong>{variant.name}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    variants: removeAt(document.variants, variantIndex),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={variant.id} onChange={(value) => onChange({
                    ...document,
                    variants: replaceAt(document.variants, variantIndex, { ...variant, id: value }),
                  })} />
                  <Field label="Name" value={variant.name} onChange={(value) => onChange({
                    ...document,
                    variants: replaceAt(document.variants, variantIndex, { ...variant, name: value }),
                  })} />
                </div>
                <div className="nested-editor">
                  <div className="nested-heading">
                    <div>
                      <strong>Hidden ground truth</strong>
                      <small>Used by the simulator only; never sent to an LLM.</small>
                    </div>
                    <button type="button" className="small-button secondary-button" onClick={() => {
                      const key = nextKey("truth", Object.keys(variant.ground_truth));
                      onChange({
                        ...document,
                        variants: replaceAt(document.variants, variantIndex, {
                          ...variant,
                          ground_truth: { ...variant.ground_truth, [key]: false },
                        }),
                      });
                    }}>Add truth field</button>
                  </div>
                  {Object.entries(variant.ground_truth).map(([key, value]) => (
                    <div className="key-value-row" key={key}>
                      <input
                        type="text"
                        aria-label="Truth key"
                        value={key}
                        onChange={(event) => {
                          const entries = Object.entries(variant.ground_truth).map(
                            ([currentKey, currentValue]) => [
                              currentKey === key ? event.target.value : currentKey,
                              currentValue,
                            ],
                          );
                          onChange({
                            ...document,
                            variants: replaceAt(document.variants, variantIndex, {
                              ...variant,
                              ground_truth: Object.fromEntries(entries),
                            }),
                          });
                        }}
                      />
                      <input
                        type="text"
                        aria-label={`Value for ${key}`}
                        value={String(value)}
                        onChange={(event) => onChange({
                          ...document,
                          variants: replaceAt(document.variants, variantIndex, {
                            ...variant,
                            ground_truth: {
                              ...variant.ground_truth,
                              [key]: scalar(event.target.value),
                            },
                          }),
                        })}
                      />
                      <button type="button" className="danger-button" onClick={() => {
                        const next = { ...variant.ground_truth };
                        delete next[key];
                        onChange({
                          ...document,
                          variants: replaceAt(document.variants, variantIndex, {
                            ...variant,
                            ground_truth: next,
                          }),
                        });
                      }}>Remove</button>
                    </div>
                  ))}
                </div>
                <div className="nested-editor">
                  <div className="nested-heading">
                    <div>
                      <strong>Investigation outcomes</strong>
                      <small>These findings remain hidden until each investigation completes.</small>
                    </div>
                  </div>
                  {document.investigations.map((investigation) => {
                    const outcomeIndex = variant.investigation_outcomes.findIndex(
                      (item) => item.investigation_id === investigation.id,
                    );
                    const selected = outcomeIndex >= 0
                      ? variant.investigation_outcomes[outcomeIndex].reveal_findings
                      : [];
                    return (
                      <div className="nested-card" key={investigation.id}>
                        <strong>{investigation.id} - {investigation.label}</strong>
                        <MultiSelect
                          label="Findings revealed"
                          options={findings}
                          selected={selected}
                          onChange={(findingIds) => {
                            const outcome = {
                              investigation_id: investigation.id,
                              reveal_findings: findingIds,
                            };
                            const outcomes = outcomeIndex >= 0
                              ? replaceAt(variant.investigation_outcomes, outcomeIndex, outcome)
                              : [...variant.investigation_outcomes, outcome];
                            onChange({
                              ...document,
                              variants: replaceAt(document.variants, variantIndex, {
                                ...variant,
                                investigation_outcomes: outcomes,
                              }),
                            });
                          }}
                          empty="Create findings first."
                        />
                      </div>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {section === "scoring" && (
        <section className="form-section">
          <Heading
            title="Minimal scoring rules"
            description="Score process and premature confidence without exposing the hidden outcome."
            addLabel="Add rule"
            onAdd={() => onChange({
              ...document,
              scoring_rules: [
                ...document.scoring_rules,
                {
                  id: nextKey("rule", document.scoring_rules.map((item) => item.id)),
                  description: "Describe the expected behavior.",
                  type: "decision_within",
                  points: 10,
                  within_minutes: 15,
                  trigger_evidence: document.observations[0]?.id ?? null,
                  target_role: null,
                  evidence_id: null,
                  decision_category: categories[0]?.id ?? null,
                  hypothesis_id: null,
                  conclusion_confidence: null,
                  confirmation_evidence: null,
                },
              ],
            })}
          />
          <div className="form-card-list">
            {document.scoring_rules.map((item, index) => (
              <article className="form-card" key={`${item.id}-${index}`}>
                <div className="form-card-heading">
                  <strong>{item.id}</strong>
                  <button type="button" className="danger-button" onClick={() => onChange({
                    ...document,
                    scoring_rules: removeAt(document.scoring_rules, index),
                  })}>Remove</button>
                </div>
                <div className="form-grid">
                  <Field label="ID" value={item.id} onChange={(value) => updateScoring(index, { ...item, id: value })} />
                  <Field label="Points" type="number" value={item.points} onChange={(value) => updateScoring(index, {
                    ...item,
                    points: Math.max(1, Number(value)),
                  })} />
                  <TextField label="Description" value={item.description} onChange={(value) => updateScoring(index, { ...item, description: value })} />
                  <label>
                    Rule type
                    <select value={item.type} onChange={(event) => updateScoring(index, {
                      ...item,
                      type: event.target.value as ScoringRuleType,
                    })}>
                      {scoringTypes.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
                    </select>
                  </label>
                  {item.type !== "avoid_premature_assessment" && (
                    <>
                      <label>
                        Trigger evidence
                        <select value={item.trigger_evidence ?? ""} onChange={(event) => updateScoring(index, {
                          ...item,
                          trigger_evidence: event.target.value || null,
                        })}>
                          <option value="">Select evidence</option>
                          {evidence.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                        </select>
                      </label>
                      <Field label="Within minutes" type="number" value={item.within_minutes ?? 1} onChange={(value) => updateScoring(index, {
                        ...item,
                        within_minutes: Math.max(1, Number(value)),
                      })} />
                    </>
                  )}
                  {(item.type === "role_contacted_within" || item.type === "evidence_shared_within") && (
                    <label>
                      Target role
                      <select value={item.target_role ?? ""} onChange={(event) => updateScoring(index, {
                        ...item,
                        target_role: event.target.value || null,
                      })}>
                        <option value="">Select role</option>
                        {roles.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                      </select>
                    </label>
                  )}
                  {item.type === "evidence_shared_within" && (
                    <label>
                      Evidence to share
                      <select value={item.evidence_id ?? ""} onChange={(event) => updateScoring(index, {
                        ...item,
                        evidence_id: event.target.value || null,
                      })}>
                        <option value="">Select evidence</option>
                        {evidence.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                      </select>
                    </label>
                  )}
                  {item.type === "decision_within" && (
                    <label>
                      Decision category
                      <select value={item.decision_category ?? ""} onChange={(event) => updateScoring(index, {
                        ...item,
                        decision_category: event.target.value || null,
                      })}>
                        <option value="">Select category</option>
                        {categories.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                      </select>
                    </label>
                  )}
                  {item.type === "avoid_premature_assessment" && (
                    <>
                      <label>
                        Hypothesis
                        <select value={item.hypothesis_id ?? ""} onChange={(event) => updateScoring(index, {
                          ...item,
                          hypothesis_id: event.target.value || null,
                        })}>
                          <option value="">Select hypothesis</option>
                          {hypotheses.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                        </select>
                      </label>
                      <label>
                        Confidence to guard
                        <select value={item.conclusion_confidence ?? ""} onChange={(event) => updateScoring(index, {
                          ...item,
                          conclusion_confidence: (event.target.value || null) as Confidence | null,
                        })}>
                          <option value="">Select confidence</option>
                          {confidenceOptions.map((value) => <option key={value}>{value}</option>)}
                        </select>
                      </label>
                      <label>
                        Confirmation evidence
                        <select value={item.confirmation_evidence ?? ""} onChange={(event) => updateScoring(index, {
                          ...item,
                          confirmation_evidence: event.target.value || null,
                        })}>
                          <option value="">Select evidence</option>
                          {evidence.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                        </select>
                      </label>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
