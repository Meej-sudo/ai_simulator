from dataclasses import dataclass, field

from app.domain.scenarios.models import (
    AllTrigger,
    AnyTrigger,
    AssessmentExistsTrigger,
    CommunicationSentTrigger,
    CompiledScenario,
    Confidence,
    DecisionRecordedTrigger,
    EventDefinition,
    EventFiredTrigger,
    EvidenceKnownTrigger,
    RuntimeScenario,
    SimulationTimeTrigger,
    TriggerDefinition,
)
from app.domain.simulation.models import EventSnapshot, EventType


_CONFIDENCE_RANK = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
    Confidence.CONFIRMED: 3,
}


@dataclass(frozen=True)
class SessionState:
    simulation_time: int
    events: list[EventSnapshot]
    evidence_by_role: dict[str, set[str]]
    fired_in_cycle: set[str] = field(default_factory=set)


class EventEngine:
    """Pure, deterministic evaluator for authored scenario events."""

    def evaluate(
        self,
        scenario: CompiledScenario | RuntimeScenario,
        state: SessionState,
    ) -> list[EventDefinition]:
        fired = {
            str(event.payload.get("event_definition_id"))
            for event in state.events
            if event.event_type == EventType.EVENT_DEFINITION_FIRED
        }
        eligible: list[EventDefinition] = []
        for definition in scenario.events:
            if definition.id in state.fired_in_cycle:
                continue
            if definition.once and definition.id in fired:
                continue
            if self.matches(definition.trigger, state):
                eligible.append(definition)
        return eligible

    def matches(self, trigger: TriggerDefinition, state: SessionState) -> bool:
        if isinstance(trigger, SimulationTimeTrigger):
            return state.simulation_time >= trigger.at_minute
        if isinstance(trigger, AssessmentExistsTrigger):
            current: dict[tuple[str, str], EventSnapshot] = {}
            for event in state.events:
                if event.event_type != EventType.ASSESSMENT_RECORDED:
                    continue
                hypothesis_id = str(event.payload.get("hypothesis_id", ""))
                if not hypothesis_id:
                    continue
                current[(event.actor_role or "", hypothesis_id)] = event
            candidates = [
                event
                for (actor, hypothesis), event in current.items()
                if hypothesis == trigger.hypothesis_id
                and (trigger.actor_role is None or actor == trigger.actor_role)
            ]
            for event in candidates:
                try:
                    confidence = Confidence(str(event.payload.get("confidence")))
                except ValueError:
                    continue
                if _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[trigger.minimum_confidence]:
                    return True
            return False
        if isinstance(trigger, EvidenceKnownTrigger):
            return trigger.evidence_id in state.evidence_by_role.get(trigger.role_id, set())
        if isinstance(trigger, DecisionRecordedTrigger):
            for event in state.events:
                if event.event_type != EventType.DECISION_MADE:
                    continue
                if event.payload.get("decision_category") != trigger.decision_category:
                    continue
                if trigger.actor_role is not None and event.actor_role != trigger.actor_role:
                    continue
                if trigger.minimum_confidence is not None:
                    try:
                        confidence = Confidence(str(event.payload.get("confidence")))
                    except ValueError:
                        continue
                    if _CONFIDENCE_RANK[confidence] < _CONFIDENCE_RANK[trigger.minimum_confidence]:
                        continue
                return True
            return False
        if isinstance(trigger, CommunicationSentTrigger):
            communication_types = {
                EventType.MESSAGE_POSTED,
                EventType.QUESTION_ASKED,
                EventType.ROLE_RESPONDED,
                EventType.TRAINEE_STAKEHOLDER_RESPONSE,
            }
            for event in state.events:
                if event.event_type not in communication_types:
                    continue
                if trigger.role_id is not None and trigger.role_id not in {
                    event.actor_role,
                    event.target_role,
                }:
                    continue
                if trigger.thread_id is not None and event.payload.get("thread_id") != trigger.thread_id:
                    continue
                return True
            return False
        if isinstance(trigger, EventFiredTrigger):
            return any(
                event.event_type == EventType.EVENT_DEFINITION_FIRED
                and event.payload.get("event_definition_id") == trigger.event_id
                for event in state.events
            )
        if isinstance(trigger, AllTrigger):
            return all(self.matches(item, state) for item in trigger.triggers)
        if isinstance(trigger, AnyTrigger):
            return any(self.matches(item, state) for item in trigger.triggers)
        return False

    def time_checkpoints(
        self,
        events: list[EventDefinition],
        old_time: int,
        new_time: int,
    ) -> list[int]:
        minutes: set[int] = set()
        for definition in events:
            self._collect_times(definition.trigger, minutes)
        return sorted(minute for minute in minutes if old_time < minute <= new_time)

    def _collect_times(self, trigger: TriggerDefinition, minutes: set[int]) -> None:
        if isinstance(trigger, SimulationTimeTrigger):
            minutes.add(trigger.at_minute)
        elif isinstance(trigger, (AllTrigger, AnyTrigger)):
            for item in trigger.triggers:
                self._collect_times(item, minutes)
