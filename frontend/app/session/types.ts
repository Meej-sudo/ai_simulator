export type Variant = { id: string; name: string };

export type DecisionCategory = {
  id: string;
  display_name: string;
  description: string;
  captures_confidence: boolean;
};

export type Scenario = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  variants: Variant[];
  decision_categories: DecisionCategory[];
};

export type Session = {
  id: string;
  scenario_id: string;
  variant_id: string;
  simulation_time: number;
  status: "created" | "running" | "completed";
};

export type Role = {
  id: string;
  display_name: string;
  responsibilities: string[];
};

export type Observation = {
  id: string;
  source: string;
  statement: string;
  reliability: string;
};

export type Finding = {
  id: string;
  statement: string;
  reliability: string;
};

export type Evidence = (Observation | Finding) & {
  kind: "observation" | "finding";
  holders?: string[];
};

export type Knowledge = {
  role_id: string;
  simulation_time: number;
  observations: Observation[];
  findings: Finding[];
};

export type InvestigationRun = {
  id: string;
  investigation_id: string;
  label: string;
  requester_role: string;
  performer_role: string;
  request: string;
  status: "in_progress" | "completed";
  started_at: number;
  due_at: number;
  completed_at: number | null;
};

export type Assessment = {
  event_id: string;
  hypothesis_id: string;
  hypothesis_key: string;
  hypothesis_label: string;
  actor_role: string;
  confidence: string;
  basis_evidence_ids: string[];
  statement: string;
  recorded_at: number;
};

export type AssessmentProjection = {
  history: Assessment[];
  current: Assessment[];
};

export type AuditEvent = {
  id: string;
  sequence: number;
  simulation_time: number;
  event_type: string;
  actor_role?: string;
  target_role?: string;
  payload: Record<string, unknown>;
};

export type Evaluation = {
  total_score: number;
  possible_score: number;
};

export type Completion = {
  sessionId: string;
  scenarioName: string;
  endedAtMinute: number;
  totalScore: number;
  possibleScore: number;
};

export type ComposerMode = "message" | "investigate" | "assess" | "decide";
