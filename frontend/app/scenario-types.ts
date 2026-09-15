export type Confidence = "low" | "medium" | "high" | "confirmed";
export type Reliability = Confidence;
export type Verbosity = "low" | "medium" | "high";

export type DecisionCategory = {
  id: string;
  display_name: string;
  description: string;
  captures_confidence: boolean;
};

export type ScenarioMetadata = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  decision_categories: DecisionCategory[];
};

export type RoleDefinition = {
  id: string;
  display_name: string;
  responsibilities: string[];
  communication_style: { tone: string; verbosity: Verbosity };
  response_guidance: string | null;
};

export type ExternalEntityDefinition = {
  id: string;
  display_name: string;
  type: string;
  accepts: string[];
};

export type ObservationDefinition = {
  id: string;
  source: string;
  statement: string;
  reliability: Reliability;
};

export type FindingDefinition = {
  id: string;
  statement: string;
  reliability: Reliability;
};

export type HypothesisDefinition = {
  id: string;
  key: string;
  label: string;
};

export type InvestigationDefinition = {
  id: string;
  label: string;
  performer_roles: string[];
  request_description: string;
  match_hints: string[];
  prerequisites: {
    all_evidence: string[];
    any_evidence: string[];
  };
  duration_minutes: number;
  repeatable: boolean;
};

export type TimelineEvent = {
  id: string;
  at_minute: number;
  type: "observation_grant";
  role: string;
  observation_ids: string[];
};

export type ObservationOverride = {
  observation_id: string;
  statement: string | null;
  reliability: Reliability | null;
};

export type TimelineOverride = {
  event_id: string;
  at_minute: number | null;
  role: string | null;
  observation_ids: string[] | null;
  enabled: boolean;
};

export type InvestigationOutcome = {
  investigation_id: string;
  reveal_findings: string[];
};

export type VariantDefinition = {
  id: string;
  name: string;
  ground_truth: Record<string, unknown>;
  observation_overrides: ObservationOverride[];
  timeline_overrides: TimelineOverride[];
  investigation_outcomes: InvestigationOutcome[];
};

export type ScoringRuleType =
  | "role_contacted_within"
  | "evidence_shared_within"
  | "decision_within"
  | "avoid_premature_assessment";

export type ScoringRule = {
  id: string;
  description: string;
  type: ScoringRuleType;
  points: number;
  within_minutes: number | null;
  trigger_evidence: string | null;
  target_role: string | null;
  evidence_id: string | null;
  decision_category: string | null;
  hypothesis_id: string | null;
  conclusion_confidence: Confidence | null;
  confirmation_evidence: string | null;
};

export type ScenarioDocument = {
  scenario: ScenarioMetadata;
  roles: RoleDefinition[];
  external_entities: ExternalEntityDefinition[];
  observations: ObservationDefinition[];
  findings: FindingDefinition[];
  hypotheses: HypothesisDefinition[];
  investigations: InvestigationDefinition[];
  timeline: TimelineEvent[];
  variants: VariantDefinition[];
  scoring_rules: ScoringRule[];
};

export type ScenarioSummary = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  variants: { id: string; name: string }[];
  decision_categories: DecisionCategory[];
};

export type AuthoringResponse = {
  scenario: ScenarioSummary;
  document: ScenarioDocument;
};
