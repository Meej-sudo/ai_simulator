from sqlalchemy.orm import Session

from app.domain.evaluation.engine import EvaluationEngine, EvaluationResult
from app.domain.knowledge.engine import KnowledgeEngine
from app.domain.scenarios.models import CONFIDENCE_SEMANTICS, Confidence, RuntimeScenario
from app.domain.simulation.models import EventSnapshot, EventType, SessionStatus
from app.domain.simulation.timeline import TimelineEngine
from app.llm.base import LLMProvider
from app.llm.models import RoleResponseRequest
from app.llm.validation import ConstrainedRoleResponder
from app.models.database import SessionRecord
from app.repositories.sessions import SessionRepository
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.scenario_registry import ScenarioRegistry


class SimulationService:
    def __init__(self, db: Session, scenarios: ScenarioRegistry, llm_provider: LLMProvider):
        self.repo = SessionRepository(db)
        self.scenarios = scenarios
        self.knowledge_engine = KnowledgeEngine()
        self.timeline_engine = TimelineEngine()
        self.evaluation_engine = EvaluationEngine()
        self.role_responder = ConstrainedRoleResponder(llm_provider)

    def create_session(
        self, scenario_id: str, variant_id: str, seed: int | None
    ) -> SessionRecord:
        try:
            self.scenarios.materialize(scenario_id, variant_id)
        except (KeyError, ValueError) as exc:
            raise NotFoundError(str(exc)) from exc
        session = self.repo.create(scenario_id, variant_id, seed)
        self.repo.commit()
        return session

    def get_session(self, session_id: str) -> SessionRecord:
        session = self.repo.get(session_id)
        if session is None:
            raise NotFoundError(f"session not found: {session_id}")
        return session

    def start(self, session_id: str) -> SessionRecord:
        session = self.get_session(session_id)
        if session.status != SessionStatus.CREATED:
            raise InvalidOperationError("only a created session can be started")
        scenario = self._runtime_scenario(session)
        session.status = SessionStatus.RUNNING
        self.repo.append_event(session.id, 0, EventType.SESSION_STARTED)
        for timeline_event in self.timeline_engine.starting_events(scenario.timeline):
            self._trigger_timeline_event(session, timeline_event)
        self.repo.commit()
        return session

    def advance_time(self, session_id: str, minutes: int) -> SessionRecord:
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        new_time = session.simulation_time + minutes
        if new_time > scenario.scenario.duration_minutes:
            raise InvalidOperationError(
                f"advance exceeds scenario duration ({scenario.scenario.duration_minutes} minutes)"
            )
        old_time = session.simulation_time
        for timeline_event in self.timeline_engine.due_events(
            scenario.timeline, old_time, new_time
        ):
            self._trigger_timeline_event(session, timeline_event)
        session.simulation_time = new_time
        self.repo.append_event(
            session.id,
            new_time,
            EventType.TIME_ADVANCED,
            payload={"from_minute": old_time, "to_minute": new_time, "minutes": minutes},
        )
        self.repo.commit()
        return session

    def complete(self, session_id: str) -> SessionRecord:
        session = self._running_session(session_id)
        session.status = SessionStatus.COMPLETED
        self.repo.append_event(
            session.id, session.simulation_time, EventType.SESSION_COMPLETED
        )
        self.repo.commit()
        return session

    def role_knowledge(self, session_id: str, role_id: str):
        session = self.get_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, role_id)
        events = self.repo.events(session.id, session.simulation_time)
        return self.knowledge_engine.get_role_knowledge(
            scenario, events, role_id, session.simulation_time
        )

    def share_fact(
        self, session_id: str, from_role: str, to_role: str, fact_id: str
    ):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, from_role)
        self._require_role(scenario, to_role)
        try:
            scenario.fact(fact_id)
        except StopIteration as exc:
            raise NotFoundError(f"fact not found: {fact_id}") from exc
        known = {fact.id for fact in self.role_knowledge(session.id, from_role)}
        if fact_id not in known:
            raise InvalidOperationError(
                f"role {from_role} cannot share a fact it does not know"
            )
        shared = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.FACT_SHARED,
            actor_role=from_role,
            target_role=to_role,
            payload={"fact_id": fact_id},
        )
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.FACT_LEARNED,
            actor_role=to_role,
            payload={"fact_id": fact_id, "source": "shared", "from_role": from_role},
        )
        self.repo.commit()
        return shared

    async def ask_role(self, session_id: str, target_role: str, message: str):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        role = self._require_role(scenario, target_role)
        facts = self.role_knowledge(session.id, target_role)
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.QUESTION_ASKED,
            target_role=target_role,
            payload={"message": message},
        )
        request = RoleResponseRequest(
            role_id=role.id,
            role_display_name=role.display_name,
            responsibilities=role.responsibilities,
            communication_style=role.communication_style,
            response_guidance=role.response_guidance,
            simulation_time=session.simulation_time,
            permitted_facts=facts,
            confidence_semantics={
                key.value: value for key, value in CONFIDENCE_SEMANTICS.items()
            },
            trainee_question=message,
        )
        validated = await self.role_responder.generate(request)
        for violation in validated.violations:
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.LLM_POLICY_VIOLATION,
                target_role=target_role,
                payload=violation,
            )
        response = validated.response
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.ROLE_RESPONDED,
            actor_role=target_role,
            payload=response.model_dump(mode="json"),
        )
        self.repo.commit()
        return response

    def make_decision(
        self,
        session_id: str,
        actor_role: str,
        category: str,
        decision: str,
        confidence: Confidence | None,
        rationale: str | None,
    ):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, actor_role)
        try:
            category_definition = scenario.scenario.decision_category(category)
        except StopIteration as exc:
            raise InvalidOperationError(
                f"decision category is not available in this scenario: {category}"
            ) from exc
        if confidence and not category_definition.captures_confidence:
            raise InvalidOperationError(
                f"decision category does not capture confidence: {category}"
            )
        event = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.DECISION_MADE,
            actor_role=actor_role,
            payload={
                "decision_category": category,
                "decision": decision,
                "confidence": confidence.value if confidence else None,
                "rationale": rationale,
            },
        )
        self.repo.commit()
        return event

    def events(self, session_id: str) -> list[EventSnapshot]:
        self.get_session(session_id)
        return self.repo.events(session_id)

    def evaluation(self, session_id: str) -> EvaluationResult:
        session = self.get_session(session_id)
        if session.status != SessionStatus.COMPLETED:
            raise InvalidOperationError(
                "evaluation is available only after the session is completed"
            )
        scenario = self._runtime_scenario(session)
        return self.evaluation_engine.evaluate(
            scenario, self.repo.events(session_id)
        )

    def roles(self, session_id: str):
        session = self.get_session(session_id)
        return self._runtime_scenario(session).roles

    def _running_session(self, session_id: str) -> SessionRecord:
        session = self.get_session(session_id)
        if session.status != SessionStatus.RUNNING:
            raise InvalidOperationError("session must be running")
        return session

    def _runtime_scenario(self, session: SessionRecord) -> RuntimeScenario:
        return self.scenarios.materialize(session.scenario_id, session.variant_id)

    @staticmethod
    def _require_role(scenario: RuntimeScenario, role_id: str):
        try:
            return scenario.role(role_id)
        except StopIteration as exc:
            raise NotFoundError(f"role not found: {role_id}") from exc

    def _trigger_timeline_event(self, session, timeline_event) -> None:
        self.repo.append_event(
            session.id,
            timeline_event.at_minute,
            EventType.TIMELINE_EVENT_TRIGGERED,
            target_role=timeline_event.role,
            payload={"timeline_event_id": timeline_event.id},
        )
        for fact_id in timeline_event.fact_ids:
            self.repo.append_event(
                session.id,
                timeline_event.at_minute,
                EventType.FACT_LEARNED,
                actor_role=timeline_event.role,
                payload={
                    "fact_id": fact_id,
                    "source": "timeline",
                    "timeline_event_id": timeline_event.id,
                },
            )
