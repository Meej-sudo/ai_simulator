from pydantic import BaseModel

from app.domain.scenarios.models import RuntimeScenario, ScoringRule
from app.domain.simulation.models import EventSnapshot, EventType


class RuleResult(BaseModel):
    rule_id: str
    description: str
    possible_points: int
    awarded_points: int
    expected_action: str
    expected_by_minute: int | None
    actual_action: str | None
    actual_minute: int | None
    relevant_event_ids: list[str]
    relevant_events: list[EventSnapshot]


class EvaluationResult(BaseModel):
    total_score: int
    possible_score: int
    rules: list[RuleResult]


class EvaluationEngine:
    def evaluate(
        self, scenario: RuntimeScenario, events: list[EventSnapshot]
    ) -> EvaluationResult:
        results = [self._evaluate_rule(rule, events) for rule in scenario.scoring_rules]
        return EvaluationResult(
            total_score=sum(item.awarded_points for item in results),
            possible_score=sum(item.possible_points for item in results),
            rules=results,
        )

    def _evaluate_rule(
        self, rule: ScoringRule, events: list[EventSnapshot]
    ) -> RuleResult:
        if rule.type == "avoid_premature_conclusion":
            return self._avoid_premature(rule, events)

        trigger = self._first_fact_learned(events, rule.trigger_fact)
        expected_by = (
            trigger.simulation_time + rule.within_minutes
            if trigger and rule.within_minutes is not None
            else None
        )
        actual = None
        expected_action = ""

        if rule.type == "role_contacted_within":
            expected_action = f"contact role {rule.target_role}"
            actual = self._first(
                events,
                lambda event: event.target_role == rule.target_role
                and event.event_type
                in {EventType.QUESTION_ASKED, EventType.FACT_SHARED}
                and (trigger is None or event.sequence > trigger.sequence),
            )
        elif rule.type == "fact_shared_within":
            expected_action = f"share fact {rule.fact_id} with role {rule.target_role}"
            actual = self._first(
                events,
                lambda event: event.event_type == EventType.FACT_SHARED
                and event.target_role == rule.target_role
                and event.payload.get("fact_id") == rule.fact_id
                and (trigger is None or event.sequence > trigger.sequence),
            )
        elif rule.type == "decision_within":
            expected_action = f"make a {rule.decision_category} decision"
            actual = self._first(
                events,
                lambda event: event.event_type == EventType.DECISION_MADE
                and event.payload.get("decision_category")
                == rule.decision_category
                and (trigger is None or event.sequence > trigger.sequence),
            )

        on_time = bool(
            trigger
            and actual
            and expected_by is not None
            and actual.simulation_time <= expected_by
        )
        relevant = [event for event in (trigger, actual) if event]
        return RuleResult(
            rule_id=rule.id,
            description=rule.description,
            possible_points=rule.points,
            awarded_points=rule.points if on_time else 0,
            expected_action=expected_action,
            expected_by_minute=expected_by,
            actual_action=(
                actual.payload.get("decision")
                if actual and actual.event_type == EventType.DECISION_MADE
                else actual.event_type if actual else None
            ),
            actual_minute=actual.simulation_time if actual else None,
            relevant_event_ids=[event.id for event in relevant],
            relevant_events=relevant,
        )

    def _avoid_premature(
        self, rule: ScoringRule, events: list[EventSnapshot]
    ) -> RuleResult:
        confirmation = self._first_fact_learned(events, rule.confirmation_fact)
        decision = self._first(
            events,
            lambda event: event.event_type == EventType.DECISION_MADE
            and event.payload.get("decision_category") == rule.decision_category
            and event.payload.get("confidence") == rule.conclusion_confidence,
        )
        premature = bool(
            decision
            and (confirmation is None or decision.sequence < confirmation.sequence)
        )
        relevant = [event for event in (confirmation, decision) if event]
        return RuleResult(
            rule_id=rule.id,
            description=rule.description,
            possible_points=rule.points,
            awarded_points=0 if premature else rule.points,
            expected_action=(
                f"avoid a {rule.conclusion_confidence} {rule.decision_category} "
                f"conclusion before {rule.confirmation_fact}"
            ),
            expected_by_minute=None,
            actual_action=decision.payload.get("decision") if decision else None,
            actual_minute=decision.simulation_time if decision else None,
            relevant_event_ids=[event.id for event in relevant],
            relevant_events=relevant,
        )

    @staticmethod
    def _first_fact_learned(
        events: list[EventSnapshot], fact_id: str | None
    ) -> EventSnapshot | None:
        return EvaluationEngine._first(
            events,
            lambda event: event.event_type == EventType.FACT_LEARNED
            and event.payload.get("fact_id") == fact_id,
        )

    @staticmethod
    def _first(events: list[EventSnapshot], predicate) -> EventSnapshot | None:
        return next((event for event in events if predicate(event)), None)
