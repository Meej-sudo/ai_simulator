from app.domain.scenarios.models import FactDefinition, RuntimeScenario
from app.domain.simulation.models import EventSnapshot, EventType


class KnowledgeEngine:
    """Derives role knowledge exclusively from auditable FACT_LEARNED events."""

    @staticmethod
    def get_role_knowledge(
        scenario: RuntimeScenario,
        events: list[EventSnapshot],
        role_id: str,
        simulation_time: int,
    ) -> list[FactDefinition]:
        known_ids: set[str] = set()
        for event in events:
            if (
                event.simulation_time <= simulation_time
                and event.event_type == EventType.FACT_LEARNED
                and event.actor_role == role_id
            ):
                fact_id = event.payload.get("fact_id")
                if fact_id:
                    known_ids.add(fact_id)
        return [fact for fact in scenario.facts if fact.id in known_ids]
