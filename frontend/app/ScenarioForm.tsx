"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import type {
  Confidence,
  PersonalityProfile,
  ScenarioDocument,
  ScoringRule,
  ScoringRuleType,
  VariantDefinition,
} from "./scenario-types";

type Section = "overview" | "roles" | "facts" | "timeline" | "variants" | "scoring";

type Props = {
  document: ScenarioDocument;
  onChange: (document: ScenarioDocument) => void;
};

const SECTIONS: { id: Section; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "roles", label: "Roles" },
  { id: "facts", label: "Facts" },
  { id: "timeline", label: "Timeline" },
  { id: "variants", label: "Variants" },
  { id: "scoring", label: "Scoring" },
];

const CONFIDENCE_LEVELS: Confidence[] = ["low", "medium", "high", "confirmed"];

const PERSONALITY_TRAITS: {
  id: keyof PersonalityProfile["traits"];
  label: string;
}[] = [
  { id: "openness", label: "Openness" },
  { id: "conscientiousness", label: "Conscientiousness" },
  { id: "extraversion", label: "Extraversion" },
  { id: "agreeableness", label: "Agreeableness" },
  { id: "emotional_stability", label: "Emotional stability" },
];

const RULE_TYPES: { id: ScoringRuleType; label: string }[] = [
  { id: "role_contacted_within", label: "Role contacted within time" },
  { id: "fact_shared_within", label: "Fact shared within time" },
  { id: "decision_within", label: "Decision made within time" },
  { id: "avoid_premature_conclusion", label: "Avoid premature conclusion" },
];

function updateAt<T>(items: T[], index: number, item: T): T[] {
  return items.map((current, currentIndex) => currentIndex === index ? item : current);
}

function removeAt<T>(items: T[], index: number): T[] {
  return items.filter((_, currentIndex) => currentIndex !== index);
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function uniqueId(prefix: string, ids: string[]): string {
  let suffix = ids.length + 1;
  while (ids.includes(`${prefix}_${suffix}`)) suffix += 1;
  return `${prefix}_${suffix}`;
}

function formatGroundTruthValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? "";
}

function parseGroundTruthValue(value: string): unknown {
  if (value === "") return "";
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function SectionHeading({ title, description, action }: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="form-section-heading">
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function CardHeading({ title, onRemove }: { title: string; onRemove: () => void }) {
  return (
    <div className="form-card-heading">
      <strong>{title}</strong>
      <button type="button" className="danger-button" onClick={onRemove}>Remove</button>
    </div>
  );
}

function ReferenceChecklist({ options, selected, onChange, emptyText }: {
  options: { id: string; label: string }[];
  selected: string[];
  onChange: (selected: string[]) => void;
  emptyText: string;
}) {
  if (options.length === 0) return <span className="field-help">{emptyText}</span>;
  return (
    <div className="reference-list">
      {options.map((option) => (
        <label className="reference-option" key={option.id}>
          <input
            type="checkbox"
            checked={selected.includes(option.id)}
            onChange={(event) => {
              onChange(event.target.checked
                ? [...selected, option.id]
                : selected.filter((item) => item !== option.id));
            }}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

function GroundTruthEditor({ value, onChange }: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const entries = Object.entries(value);

  function replaceEntry(index: number, key: string, entryValue: unknown) {
    const existingKey = entries[index]?.[0];
    if (key !== existingKey && Object.prototype.hasOwnProperty.call(value, key)) return;
    const next = [...entries];
    next[index] = [key, entryValue];
    onChange(Object.fromEntries(next));
  }

  function addEntry() {
    const key = uniqueId("new_value", Object.keys(value));
    onChange({ ...value, [key]: "" });
  }

  return (
    <div className="nested-editor">
      <div className="nested-heading">
        <div>
          <strong>Ground truth</strong>
          <small>Values accept text, numbers, true/false, or JSON.</small>
        </div>
        <button type="button" className="secondary-button small-button" onClick={addEntry}>
          Add value
        </button>
      </div>
      {entries.map(([key, entryValue], index) => (
        <div className="key-value-row" key={`${key}-${index}`}>
          <label>
            Key
            <input
              type="text"
              value={key}
              onChange={(event) => replaceEntry(index, event.target.value, entryValue)}
            />
          </label>
          <label>
            Value
            <input
              type="text"
              value={formatGroundTruthValue(entryValue)}
              onChange={(event) => replaceEntry(
                index,
                key,
                parseGroundTruthValue(event.target.value),
              )}
            />
          </label>
          <button
            type="button"
            className="danger-button compact-button"
            onClick={() => onChange(Object.fromEntries(
              entries.filter((_, currentIndex) => currentIndex !== index),
            ))}
          >
            Remove
          </button>
        </div>
      ))}
    </div>
  );
}

function ruleWithType(
  rule: ScoringRule,
  type: ScoringRuleType,
  document: ScenarioDocument,
): ScoringRule {
  const next: ScoringRule = {
    ...rule,
    type,
    within_minutes: null,
    trigger_fact: null,
    target_role: null,
    fact_id: null,
    decision_category: null,
    conclusion_confidence: null,
    confirmation_fact: null,
  };
  const firstFact = document.facts[0]?.id ?? null;
  const firstRole = document.roles[0]?.id ?? null;
  const firstCategory = document.scenario.decision_categories[0]?.id ?? null;

  if (type === "role_contacted_within") {
    return { ...next, trigger_fact: firstFact, target_role: firstRole, within_minutes: 30 };
  }
  if (type === "fact_shared_within") {
    return {
      ...next,
      trigger_fact: firstFact,
      fact_id: firstFact,
      target_role: firstRole,
      within_minutes: 30,
    };
  }
  if (type === "decision_within") {
    return {
      ...next,
      trigger_fact: firstFact,
      decision_category: firstCategory,
      within_minutes: 30,
    };
  }
  return {
    ...next,
    decision_category: firstCategory,
    conclusion_confidence: "confirmed",
    confirmation_fact: firstFact,
  };
}

export default function ScenarioForm({ document, onChange }: Props) {
  const [section, setSection] = useState<Section>("overview");
  const roleOptions = document.roles.map((item) => ({ id: item.id, label: item.display_name }));
  const factOptions = document.facts.map((item) => ({ id: item.id, label: `${item.id} · ${item.statement}` }));
  const eventOptions = document.timeline.map((item) => ({ id: item.id, label: `${item.id} · T+${item.at_minute}` }));
  const categoryOptions = document.scenario.decision_categories.map((item) => ({
    id: item.id,
    label: item.display_name,
  }));

  function renameCategory(index: number, id: string) {
    const previous = document.scenario.decision_categories[index].id;
    onChange({
      ...document,
      scenario: {
        ...document.scenario,
        decision_categories: updateAt(
          document.scenario.decision_categories,
          index,
          { ...document.scenario.decision_categories[index], id },
        ),
      },
      scoring_rules: document.scoring_rules.map((rule) => ({
        ...rule,
        decision_category: rule.decision_category === previous ? id : rule.decision_category,
      })),
    });
  }

  function renameRole(index: number, id: string) {
    const previous = document.roles[index].id;
    onChange({
      ...document,
      roles: updateAt(document.roles, index, { ...document.roles[index], id }),
      timeline: document.timeline.map((event) => ({
        ...event,
        role: event.role === previous ? id : event.role,
      })),
      variants: document.variants.map((variant) => ({
        ...variant,
        timeline_overrides: variant.timeline_overrides.map((override) => ({
          ...override,
          role: override.role === previous ? id : override.role,
        })),
      })),
      scoring_rules: document.scoring_rules.map((rule) => ({
        ...rule,
        target_role: rule.target_role === previous ? id : rule.target_role,
      })),
    });
  }

  function renameFact(index: number, id: string) {
    const previous = document.facts[index].id;
    const rename = (current: string) => current === previous ? id : current;
    onChange({
      ...document,
      facts: updateAt(document.facts, index, { ...document.facts[index], id }),
      timeline: document.timeline.map((event) => ({
        ...event,
        fact_ids: event.fact_ids.map(rename),
      })),
      variants: document.variants.map((variant) => ({
        ...variant,
        fact_overrides: variant.fact_overrides.map((override) => ({
          ...override,
          fact_id: rename(override.fact_id),
        })),
        timeline_overrides: variant.timeline_overrides.map((override) => ({
          ...override,
          fact_ids: override.fact_ids?.map(rename) ?? null,
        })),
      })),
      scoring_rules: document.scoring_rules.map((rule) => ({
        ...rule,
        trigger_fact: rule.trigger_fact === previous ? id : rule.trigger_fact,
        fact_id: rule.fact_id === previous ? id : rule.fact_id,
        confirmation_fact: rule.confirmation_fact === previous ? id : rule.confirmation_fact,
      })),
    });
  }

  function renameEvent(index: number, id: string) {
    const previous = document.timeline[index].id;
    onChange({
      ...document,
      timeline: updateAt(document.timeline, index, { ...document.timeline[index], id }),
      variants: document.variants.map((variant) => ({
        ...variant,
        timeline_overrides: variant.timeline_overrides.map((override) => ({
          ...override,
          event_id: override.event_id === previous ? id : override.event_id,
        })),
      })),
    });
  }

  function updateVariant(index: number, variant: VariantDefinition) {
    onChange({ ...document, variants: updateAt(document.variants, index, variant) });
  }

  return (
    <div className="scenario-form">
      <nav className="form-tabs" aria-label="Scenario form sections">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={section === item.id ? "active" : ""}
            aria-pressed={section === item.id}
            onClick={() => setSection(item.id)}
          >
            {item.label}
            <span>{
              item.id === "roles" ? document.roles.length
                : item.id === "facts" ? document.facts.length
                  : item.id === "timeline" ? document.timeline.length
                    : item.id === "variants" ? document.variants.length
                      : item.id === "scoring" ? document.scoring_rules.length
                        : ""
            }</span>
          </button>
        ))}
      </nav>

      {section === "overview" && (
        <div className="form-section">
          <SectionHeading
            title="Scenario overview"
            description="Public metadata and the broad decision categories shown to trainees."
          />
          <div className="form-grid">
            <label>
              Scenario ID
              <input type="text" value={document.scenario.id} readOnly />
              <small className="field-help">The ID cannot be changed after creation.</small>
            </label>
            <label>
              Duration in minutes
              <input
                type="number"
                min={1}
                value={document.scenario.duration_minutes}
                onChange={(event) => onChange({
                  ...document,
                  scenario: {
                    ...document.scenario,
                    duration_minutes: Number(event.target.value),
                  },
                })}
              />
            </label>
            <label className="wide-field">
              Scenario name
              <input
                type="text"
                value={document.scenario.name}
                onChange={(event) => onChange({
                  ...document,
                  scenario: { ...document.scenario, name: event.target.value },
                })}
              />
            </label>
            <label className="wide-field">
              Description
              <textarea
                rows={3}
                value={document.scenario.description}
                onChange={(event) => onChange({
                  ...document,
                  scenario: { ...document.scenario, description: event.target.value },
                })}
              />
            </label>
          </div>

          <SectionHeading
            title="Decision categories"
            description="Broad labels available when trainees record free-text decisions."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => {
                  const categories = document.scenario.decision_categories;
                  onChange({
                    ...document,
                    scenario: {
                      ...document.scenario,
                      decision_categories: [
                        ...categories,
                        {
                          id: uniqueId("category", categories.map((item) => item.id)),
                          display_name: "New category",
                          description: "",
                          captures_confidence: false,
                        },
                      ],
                    },
                  });
                }}
              >
                Add category
              </button>
            )}
          />
          <div className="form-card-list">
            {document.scenario.decision_categories.map((category, index) => (
              <div className="form-card" key={`${category.id}-${index}`}>
                <CardHeading
                  title={category.display_name || `Category ${index + 1}`}
                  onRemove={() => onChange({
                    ...document,
                    scenario: {
                      ...document.scenario,
                      decision_categories: removeAt(
                        document.scenario.decision_categories,
                        index,
                      ),
                    },
                  })}
                />
                <div className="form-grid">
                  <label>
                    Category ID
                    <input
                      type="text"
                      value={category.id}
                      onChange={(event) => renameCategory(index, event.target.value)}
                    />
                  </label>
                  <label>
                    Display name
                    <input
                      type="text"
                      value={category.display_name}
                      onChange={(event) => onChange({
                        ...document,
                        scenario: {
                          ...document.scenario,
                          decision_categories: updateAt(
                            document.scenario.decision_categories,
                            index,
                            { ...category, display_name: event.target.value },
                          ),
                        },
                      })}
                    />
                  </label>
                  <label className="wide-field">
                    Description
                    <textarea
                      rows={2}
                      value={category.description}
                      onChange={(event) => onChange({
                        ...document,
                        scenario: {
                          ...document.scenario,
                          decision_categories: updateAt(
                            document.scenario.decision_categories,
                            index,
                            { ...category, description: event.target.value },
                          ),
                        },
                      })}
                    />
                  </label>
                  <label className="check-field wide-field">
                    <input
                      type="checkbox"
                      checked={category.captures_confidence}
                      onChange={(event) => onChange({
                        ...document,
                        scenario: {
                          ...document.scenario,
                          decision_categories: updateAt(
                            document.scenario.decision_categories,
                            index,
                            { ...category, captures_confidence: event.target.checked },
                          ),
                        },
                      })}
                    />
                    Ask trainees to record confidence for this category
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "roles" && (
        <div className="form-section">
          <SectionHeading
            title="Exercise roles"
            description="People the trainee can question, their responsibilities, and speaking style."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => onChange({
                  ...document,
                  roles: [
                    ...document.roles,
                    {
                      id: uniqueId("role", document.roles.map((item) => item.id)),
                      display_name: "New role",
                      responsibilities: ["Describe this role's responsibility"],
                      communication_style: { tone: "professional", verbosity: "medium" },
                      personality: {
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
                      },
                      response_guidance: null,
                    },
                  ],
                })}
              >
                Add role
              </button>
            )}
          />
          <div className="form-card-list">
            {document.roles.map((role, index) => (
              <div className="form-card" key={`${role.id}-${index}`}>
                <CardHeading
                  title={role.display_name || `Role ${index + 1}`}
                  onRemove={() => onChange({
                    ...document,
                    roles: removeAt(document.roles, index),
                  })}
                />
                <div className="form-grid">
                  <label>
                    Role ID
                    <input
                      type="text"
                      value={role.id}
                      onChange={(event) => renameRole(index, event.target.value)}
                    />
                  </label>
                  <label>
                    Display name
                    <input
                      type="text"
                      value={role.display_name}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          display_name: event.target.value,
                        }),
                      })}
                    />
                  </label>
                  <label>
                    Tone
                    <input
                      type="text"
                      value={role.communication_style.tone}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          communication_style: {
                            ...role.communication_style,
                            tone: event.target.value,
                          },
                        }),
                      })}
                    />
                  </label>
                  <label>
                    Verbosity
                    <select
                      value={role.communication_style.verbosity}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          communication_style: {
                            ...role.communication_style,
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
                  <label className="wide-field">
                    Responsibilities (one per line)
                    <textarea
                      rows={4}
                      value={role.responsibilities.join("\n")}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          responsibilities: lines(event.target.value),
                        }),
                      })}
                    />
                  </label>
                  <label className="wide-field">
                    Personality summary
                    <textarea
                      rows={2}
                      value={role.personality.summary}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          personality: {
                            ...role.personality,
                            summary: event.target.value,
                          },
                        }),
                      })}
                    />
                  </label>
                  {PERSONALITY_TRAITS.map((trait) => (
                    <label key={trait.id}>
                      {trait.label}
                      <select
                        value={role.personality.traits[trait.id]}
                        onChange={(event) => onChange({
                          ...document,
                          roles: updateAt(document.roles, index, {
                            ...role,
                            personality: {
                              ...role.personality,
                              traits: {
                                ...role.personality.traits,
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
                  <label className="wide-field">
                    Behavioral tendencies (one per line)
                    <textarea
                      rows={4}
                      value={role.personality.behavioral_tendencies.join("\n")}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          personality: {
                            ...role.personality,
                            behavioral_tendencies: lines(event.target.value),
                          },
                        }),
                      })}
                    />
                  </label>
                  <label className="wide-field">
                    Behavior under pressure
                    <textarea
                      rows={2}
                      value={role.personality.under_pressure}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          personality: {
                            ...role.personality,
                            under_pressure: event.target.value,
                          },
                        }),
                      })}
                    />
                  </label>
                  <label className="wide-field">
                    Additional response guidance
                    <textarea
                      rows={3}
                      value={role.response_guidance ?? ""}
                      onChange={(event) => onChange({
                        ...document,
                        roles: updateAt(document.roles, index, {
                          ...role,
                          response_guidance: event.target.value || null,
                        }),
                      })}
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "facts" && (
        <div className="form-section">
          <SectionHeading
            title="Incident facts"
            description="Observations and assessments that can be revealed to roles over time."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => onChange({
                  ...document,
                  facts: [
                    ...document.facts,
                    {
                      id: uniqueId("F", document.facts.map((item) => item.id)),
                      type: "observation",
                      statement: "Describe the new incident fact.",
                      confidence: "medium",
                    },
                  ],
                })}
              >
                Add fact
              </button>
            )}
          />
          <div className="form-card-list">
            {document.facts.map((fact, index) => (
              <div className="form-card" key={`${fact.id}-${index}`}>
                <CardHeading
                  title={`${fact.id || "Fact"} · ${fact.type}`}
                  onRemove={() => onChange({
                    ...document,
                    facts: removeAt(document.facts, index),
                  })}
                />
                <div className="form-grid">
                  <label>
                    Fact ID
                    <input
                      type="text"
                      value={fact.id}
                      onChange={(event) => renameFact(index, event.target.value)}
                    />
                  </label>
                  <label>
                    Type
                    <select
                      value={fact.type}
                      onChange={(event) => onChange({
                        ...document,
                        facts: updateAt(document.facts, index, {
                          ...fact,
                          type: event.target.value as "observation" | "assessment",
                        }),
                      })}
                    >
                      <option value="observation">Observation</option>
                      <option value="assessment">Assessment</option>
                    </select>
                  </label>
                  <label>
                    Confidence
                    <select
                      value={fact.confidence}
                      onChange={(event) => onChange({
                        ...document,
                        facts: updateAt(document.facts, index, {
                          ...fact,
                          confidence: event.target.value as Confidence,
                        }),
                      })}
                    >
                      {CONFIDENCE_LEVELS.map((level) => (
                        <option value={level} key={level}>{level}</option>
                      ))}
                    </select>
                  </label>
                  <label className="wide-field">
                    Statement
                    <textarea
                      rows={3}
                      value={fact.statement}
                      onChange={(event) => onChange({
                        ...document,
                        facts: updateAt(document.facts, index, {
                          ...fact,
                          statement: event.target.value,
                        }),
                      })}
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "timeline" && (
        <div className="form-section">
          <SectionHeading
            title="Timeline events"
            description="Choose when each role learns one or more facts."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => onChange({
                  ...document,
                  timeline: [
                    ...document.timeline,
                    {
                      id: uniqueId("E", document.timeline.map((item) => item.id)),
                      at_minute: 0,
                      type: "knowledge_grant",
                      role: document.roles[0]?.id ?? "",
                      fact_ids: document.facts[0] ? [document.facts[0].id] : [],
                    },
                  ],
                })}
              >
                Add event
              </button>
            )}
          />
          <div className="form-card-list">
            {document.timeline.map((event, index) => (
              <div className="form-card" key={`${event.id}-${index}`}>
                <CardHeading
                  title={`${event.id || "Event"} · T+${event.at_minute}`}
                  onRemove={() => onChange({
                    ...document,
                    timeline: removeAt(document.timeline, index),
                  })}
                />
                <div className="form-grid">
                  <label>
                    Event ID
                    <input
                      type="text"
                      value={event.id}
                      onChange={(change) => renameEvent(index, change.target.value)}
                    />
                  </label>
                  <label>
                    At minute
                    <input
                      type="number"
                      min={0}
                      value={event.at_minute}
                      onChange={(change) => onChange({
                        ...document,
                        timeline: updateAt(document.timeline, index, {
                          ...event,
                          at_minute: Number(change.target.value),
                        }),
                      })}
                    />
                  </label>
                  <label>
                    Recipient role
                    <select
                      value={event.role}
                      onChange={(change) => onChange({
                        ...document,
                        timeline: updateAt(document.timeline, index, {
                          ...event,
                          role: change.target.value,
                        }),
                      })}
                    >
                      <option value="">Select a role</option>
                      {roleOptions.map((option) => (
                        <option value={option.id} key={option.id}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <div className="field-group wide-field">
                    <span className="field-label">Facts revealed</span>
                    <ReferenceChecklist
                      options={factOptions}
                      selected={event.fact_ids}
                      emptyText="Create facts before assigning them to the timeline."
                      onChange={(factIds) => onChange({
                        ...document,
                        timeline: updateAt(document.timeline, index, {
                          ...event,
                          fact_ids: factIds,
                        }),
                      })}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "variants" && (
        <div className="form-section">
          <SectionHeading
            title="Scenario variants"
            description="Hidden ground truth and per-track fact or timeline differences."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => onChange({
                  ...document,
                  variants: [
                    ...document.variants,
                    {
                      id: uniqueId("track", document.variants.map((item) => item.id)),
                      name: "New track",
                      ground_truth: {},
                      fact_overrides: [],
                      timeline_overrides: [],
                    },
                  ],
                })}
              >
                Add variant
              </button>
            )}
          />
          <div className="form-card-list">
            {document.variants.map((variant, variantIndex) => (
              <div className="form-card variant-card" key={`${variant.id}-${variantIndex}`}>
                <CardHeading
                  title={variant.name || `Variant ${variantIndex + 1}`}
                  onRemove={() => onChange({
                    ...document,
                    variants: removeAt(document.variants, variantIndex),
                  })}
                />
                <div className="form-grid">
                  <label>
                    Variant ID
                    <input
                      type="text"
                      value={variant.id}
                      onChange={(event) => updateVariant(variantIndex, {
                        ...variant,
                        id: event.target.value,
                      })}
                    />
                  </label>
                  <label>
                    Display name
                    <input
                      type="text"
                      value={variant.name}
                      onChange={(event) => updateVariant(variantIndex, {
                        ...variant,
                        name: event.target.value,
                      })}
                    />
                  </label>
                </div>

                <GroundTruthEditor
                  value={variant.ground_truth}
                  onChange={(groundTruth) => updateVariant(variantIndex, {
                    ...variant,
                    ground_truth: groundTruth,
                  })}
                />

                <div className="nested-editor">
                  <div className="nested-heading">
                    <div>
                      <strong>Fact overrides</strong>
                      <small>Change a fact statement or confidence only for this variant.</small>
                    </div>
                    <button
                      type="button"
                      className="secondary-button small-button"
                      onClick={() => updateVariant(variantIndex, {
                        ...variant,
                        fact_overrides: [
                          ...variant.fact_overrides,
                          {
                            fact_id: document.facts[0]?.id ?? "",
                            statement: null,
                            confidence: null,
                          },
                        ],
                      })}
                    >
                      Add fact override
                    </button>
                  </div>
                  {variant.fact_overrides.map((override, overrideIndex) => (
                    <div className="nested-card" key={`${override.fact_id}-${overrideIndex}`}>
                      <div className="form-grid">
                        <label>
                          Fact
                          <select
                            value={override.fact_id}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              fact_overrides: updateAt(
                                variant.fact_overrides,
                                overrideIndex,
                                { ...override, fact_id: event.target.value },
                              ),
                            })}
                          >
                            <option value="">Select a fact</option>
                            {factOptions.map((option) => (
                              <option value={option.id} key={option.id}>{option.label}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Confidence override
                          <select
                            value={override.confidence ?? ""}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              fact_overrides: updateAt(
                                variant.fact_overrides,
                                overrideIndex,
                                {
                                  ...override,
                                  confidence: (event.target.value || null) as Confidence | null,
                                },
                              ),
                            })}
                          >
                            <option value="">Keep original</option>
                            {CONFIDENCE_LEVELS.map((level) => (
                              <option value={level} key={level}>{level}</option>
                            ))}
                          </select>
                        </label>
                        <label className="wide-field">
                          Statement override
                          <textarea
                            rows={2}
                            placeholder="Leave blank to keep the original statement."
                            value={override.statement ?? ""}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              fact_overrides: updateAt(
                                variant.fact_overrides,
                                overrideIndex,
                                { ...override, statement: event.target.value || null },
                              ),
                            })}
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        className="danger-button small-button"
                        onClick={() => updateVariant(variantIndex, {
                          ...variant,
                          fact_overrides: removeAt(
                            variant.fact_overrides,
                            overrideIndex,
                          ),
                        })}
                      >
                        Remove override
                      </button>
                    </div>
                  ))}
                </div>

                <div className="nested-editor">
                  <div className="nested-heading">
                    <div>
                      <strong>Timeline overrides</strong>
                      <small>Move, redirect, change, or disable a base timeline event.</small>
                    </div>
                    <button
                      type="button"
                      className="secondary-button small-button"
                      onClick={() => updateVariant(variantIndex, {
                        ...variant,
                        timeline_overrides: [
                          ...variant.timeline_overrides,
                          {
                            event_id: document.timeline[0]?.id ?? "",
                            at_minute: null,
                            role: null,
                            fact_ids: null,
                            enabled: true,
                          },
                        ],
                      })}
                    >
                      Add timeline override
                    </button>
                  </div>
                  {variant.timeline_overrides.map((override, overrideIndex) => (
                    <div className="nested-card" key={`${override.event_id}-${overrideIndex}`}>
                      <div className="form-grid">
                        <label>
                          Base event
                          <select
                            value={override.event_id}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              timeline_overrides: updateAt(
                                variant.timeline_overrides,
                                overrideIndex,
                                { ...override, event_id: event.target.value },
                              ),
                            })}
                          >
                            <option value="">Select an event</option>
                            {eventOptions.map((option) => (
                              <option value={option.id} key={option.id}>{option.label}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          Minute override
                          <input
                            type="number"
                            min={0}
                            placeholder="Keep original"
                            value={override.at_minute ?? ""}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              timeline_overrides: updateAt(
                                variant.timeline_overrides,
                                overrideIndex,
                                {
                                  ...override,
                                  at_minute: event.target.value === ""
                                    ? null
                                    : Number(event.target.value),
                                },
                              ),
                            })}
                          />
                        </label>
                        <label>
                          Role override
                          <select
                            value={override.role ?? ""}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              timeline_overrides: updateAt(
                                variant.timeline_overrides,
                                overrideIndex,
                                { ...override, role: event.target.value || null },
                              ),
                            })}
                          >
                            <option value="">Keep original</option>
                            {roleOptions.map((option) => (
                              <option value={option.id} key={option.id}>{option.label}</option>
                            ))}
                          </select>
                        </label>
                        <label className="check-field">
                          <input
                            type="checkbox"
                            checked={override.enabled}
                            onChange={(event) => updateVariant(variantIndex, {
                              ...variant,
                              timeline_overrides: updateAt(
                                variant.timeline_overrides,
                                overrideIndex,
                                { ...override, enabled: event.target.checked },
                              ),
                            })}
                          />
                          Event enabled
                        </label>
                        <div className="field-group wide-field">
                          <span className="field-label">Fact override</span>
                          <span className="field-help">No selection keeps the base facts.</span>
                          <ReferenceChecklist
                            options={factOptions}
                            selected={override.fact_ids ?? []}
                            emptyText="Create facts before overriding this event."
                            onChange={(factIds) => updateVariant(variantIndex, {
                              ...variant,
                              timeline_overrides: updateAt(
                                variant.timeline_overrides,
                                overrideIndex,
                                {
                                  ...override,
                                  fact_ids: factIds.length > 0 ? factIds : null,
                                },
                              ),
                            })}
                          />
                        </div>
                      </div>
                      <button
                        type="button"
                        className="danger-button small-button"
                        onClick={() => updateVariant(variantIndex, {
                          ...variant,
                          timeline_overrides: removeAt(
                            variant.timeline_overrides,
                            overrideIndex,
                          ),
                        })}
                      >
                        Remove override
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "scoring" && (
        <div className="form-section">
          <SectionHeading
            title="Scoring rules"
            description="Deterministic criteria evaluated from the exercise event log."
            action={(
              <button
                type="button"
                className="secondary-button small-button"
                onClick={() => {
                  const base: ScoringRule = {
                    id: uniqueId("rule", document.scoring_rules.map((item) => item.id)),
                    description: "Describe the expected response.",
                    type: "decision_within",
                    points: 10,
                    within_minutes: null,
                    trigger_fact: null,
                    target_role: null,
                    fact_id: null,
                    decision_category: null,
                    conclusion_confidence: null,
                    confirmation_fact: null,
                  };
                  onChange({
                    ...document,
                    scoring_rules: [
                      ...document.scoring_rules,
                      ruleWithType(base, "decision_within", document),
                    ],
                  });
                }}
              >
                Add rule
              </button>
            )}
          />
          <div className="form-card-list">
            {document.scoring_rules.map((rule, index) => (
              <div className="form-card" key={`${rule.id}-${index}`}>
                <CardHeading
                  title={rule.description || `Rule ${index + 1}`}
                  onRemove={() => onChange({
                    ...document,
                    scoring_rules: removeAt(document.scoring_rules, index),
                  })}
                />
                <div className="form-grid">
                  <label>
                    Rule ID
                    <input
                      type="text"
                      value={rule.id}
                      onChange={(event) => onChange({
                        ...document,
                        scoring_rules: updateAt(document.scoring_rules, index, {
                          ...rule,
                          id: event.target.value,
                        }),
                      })}
                    />
                  </label>
                  <label>
                    Rule type
                    <select
                      value={rule.type}
                      onChange={(event) => onChange({
                        ...document,
                        scoring_rules: updateAt(
                          document.scoring_rules,
                          index,
                          ruleWithType(rule, event.target.value as ScoringRuleType, document),
                        ),
                      })}
                    >
                      {RULE_TYPES.map((type) => (
                        <option value={type.id} key={type.id}>{type.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Points
                    <input
                      type="number"
                      min={1}
                      value={rule.points}
                      onChange={(event) => onChange({
                        ...document,
                        scoring_rules: updateAt(document.scoring_rules, index, {
                          ...rule,
                          points: Number(event.target.value),
                        }),
                      })}
                    />
                  </label>
                  <label className="wide-field">
                    Description
                    <textarea
                      rows={2}
                      value={rule.description}
                      onChange={(event) => onChange({
                        ...document,
                        scoring_rules: updateAt(document.scoring_rules, index, {
                          ...rule,
                          description: event.target.value,
                        }),
                      })}
                    />
                  </label>

                  {rule.type !== "avoid_premature_conclusion" && (
                    <label>
                      Trigger fact
                      <select
                        value={rule.trigger_fact ?? ""}
                        onChange={(event) => onChange({
                          ...document,
                          scoring_rules: updateAt(document.scoring_rules, index, {
                            ...rule,
                            trigger_fact: event.target.value || null,
                          }),
                        })}
                      >
                        <option value="">Select a fact</option>
                        {factOptions.map((option) => (
                          <option value={option.id} key={option.id}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {(rule.type === "role_contacted_within" || rule.type === "fact_shared_within") && (
                    <label>
                      Target role
                      <select
                        value={rule.target_role ?? ""}
                        onChange={(event) => onChange({
                          ...document,
                          scoring_rules: updateAt(document.scoring_rules, index, {
                            ...rule,
                            target_role: event.target.value || null,
                          }),
                        })}
                      >
                        <option value="">Select a role</option>
                        {roleOptions.map((option) => (
                          <option value={option.id} key={option.id}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {rule.type === "fact_shared_within" && (
                    <label>
                      Fact that must be shared
                      <select
                        value={rule.fact_id ?? ""}
                        onChange={(event) => onChange({
                          ...document,
                          scoring_rules: updateAt(document.scoring_rules, index, {
                            ...rule,
                            fact_id: event.target.value || null,
                          }),
                        })}
                      >
                        <option value="">Select a fact</option>
                        {factOptions.map((option) => (
                          <option value={option.id} key={option.id}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {(rule.type === "decision_within" || rule.type === "avoid_premature_conclusion") && (
                    <label>
                      Decision category
                      <select
                        value={rule.decision_category ?? ""}
                        onChange={(event) => onChange({
                          ...document,
                          scoring_rules: updateAt(document.scoring_rules, index, {
                            ...rule,
                            decision_category: event.target.value || null,
                          }),
                        })}
                      >
                        <option value="">Select a category</option>
                        {categoryOptions.map((option) => (
                          <option value={option.id} key={option.id}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {rule.type !== "avoid_premature_conclusion" && (
                    <label>
                      Complete within minutes
                      <input
                        type="number"
                        min={1}
                        value={rule.within_minutes ?? ""}
                        onChange={(event) => onChange({
                          ...document,
                          scoring_rules: updateAt(document.scoring_rules, index, {
                            ...rule,
                            within_minutes: event.target.value === ""
                              ? null
                              : Number(event.target.value),
                          }),
                        })}
                      />
                    </label>
                  )}

                  {rule.type === "avoid_premature_conclusion" && (
                    <>
                      <label>
                        Premature confidence
                        <select
                          value={rule.conclusion_confidence ?? ""}
                          onChange={(event) => onChange({
                            ...document,
                            scoring_rules: updateAt(document.scoring_rules, index, {
                              ...rule,
                              conclusion_confidence: (event.target.value || null) as Confidence | null,
                            }),
                          })}
                        >
                          <option value="">Select confidence</option>
                          {CONFIDENCE_LEVELS.map((level) => (
                            <option value={level} key={level}>{level}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Confirmation fact
                        <select
                          value={rule.confirmation_fact ?? ""}
                          onChange={(event) => onChange({
                            ...document,
                            scoring_rules: updateAt(document.scoring_rules, index, {
                              ...rule,
                              confirmation_fact: event.target.value || null,
                            }),
                          })}
                        >
                          <option value="">Select a fact</option>
                          {factOptions.map((option) => (
                            <option value={option.id} key={option.id}>{option.label}</option>
                          ))}
                        </select>
                      </label>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
