export type Confidence = "low" | "medium" | "high" | "confirmed";
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

export type FactDefinition = {
  id: string;
  type: "observation" | "assessment";
  statement: string;
  confidence: Confidence;
};

export type TimelineEvent = {
  id: string;
  at_minute: number;
  type: "knowledge_grant";
  role: string;
  fact_ids: string[];
};

export type FactOverride = {
  fact_id: string;
  statement: string | null;
  confidence: Confidence | null;
};

export type TimelineOverride = {
  event_id: string;
  at_minute: number | null;
  role: string | null;
  fact_ids: string[] | null;
  enabled: boolean;
};

export type VariantDefinition = {
  id: string;
  name: string;
  ground_truth: Record<string, unknown>;
  fact_overrides: FactOverride[];
  timeline_overrides: TimelineOverride[];
};

export type ScoringRuleType =
  | "role_contacted_within"
  | "fact_shared_within"
  | "decision_within"
  | "avoid_premature_conclusion";

export type ScoringRule = {
  id: string;
  description: string;
  type: ScoringRuleType;
  points: number;
  within_minutes: number | null;
  trigger_fact: string | null;
  target_role: string | null;
  fact_id: string | null;
  decision_category: string | null;
  conclusion_confidence: Confidence | null;
  confirmation_fact: string | null;
};

export type ScenarioDocument = {
  scenario: ScenarioMetadata;
  roles: RoleDefinition[];
  facts: FactDefinition[];
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
