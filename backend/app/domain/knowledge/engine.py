from pydantic import BaseModel

from app.domain.scenarios.models import (
    FindingDefinition,
    ObservationDefinition,
    RuntimeScenario,
)
from app.domain.simulation.models import EventSnapshot, EventType


class RoleKnowledge(BaseModel):
    role_id: str
    simulation_time: int
    observations: list[ObservationDefinition]
    findings: list[FindingDefinition]

    @property
    def evidence_ids(self) -> set[str]:
        return {item.id for item in [*self.observations, *self.findings]}


class KnowledgeEngine:
    """Derives role-scoped observations and findings from the event stream."""

    @staticmethod
    def get_role_knowledge(
        scenario: RuntimeScenario,
        events: list[EventSnapshot],
        role_id: str,
        simulation_time: int,
    ) -> RoleKnowledge:
        observation_ids: set[str] = set()
        finding_ids: set[str] = set()
        known_observations = {item.id for item in scenario.observations}
        known_findings = {item.id for item in scenario.findings}

        for event in events:
            if event.simulation_time > simulation_time:
                continue
            if (
                event.event_type == EventType.OBSERVATION_REVEALED
                and event.actor_role == role_id
            ):
                observation_id = event.payload.get("observation_id")
                if observation_id in known_observations:
                    observation_ids.add(observation_id)
            elif (
                event.event_type == EventType.FINDING_REVEALED
                and event.actor_role == role_id
            ):
                finding_id = event.payload.get("finding_id")
                if finding_id in known_findings:
                    finding_ids.add(finding_id)
            elif (
                event.event_type == EventType.EVIDENCE_SHARED
                and event.target_role == role_id
            ):
                evidence_id = event.payload.get("evidence_id")
                if evidence_id in known_observations:
                    observation_ids.add(evidence_id)
                elif evidence_id in known_findings:
                    finding_ids.add(evidence_id)

        return RoleKnowledge(
            role_id=role_id,
            simulation_time=simulation_time,
            observations=[
                item for item in scenario.observations if item.id in observation_ids
            ],
            findings=[item for item in scenario.findings if item.id in finding_ids],
        )
