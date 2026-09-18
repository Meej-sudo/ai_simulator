from sqlalchemy.orm import Session

from app.domain.evaluation.engine import EvaluationEngine, EvaluationResult
from app.domain.knowledge.engine import KnowledgeEngine, RoleKnowledge
from app.domain.scenarios.models import (
    CONFIDENCE_SEMANTICS,
    Confidence,
    Reliability,
    RuntimeScenario,
)
from app.domain.simulation.models import (
    AssessmentProjection,
    AssessmentSnapshot,
    EventSnapshot,
    EventType,
    InvestigationRequestResult,
    InvestigationRun,
    InvestigationStatus,
    SessionStatus,
)
from app.domain.simulation.timeline import TimelineEngine
from app.llm.base import LLMProvider
from app.llm.models import (
    AssessmentInterpretationRequest,
    EligibleInvestigation,
    InvestigationInterpretationRequest,
    RoleResponseRequest,
    ThreadTurn,
)
from app.llm.validation import (
    ConstrainedAssessmentInterpreter,
    ConstrainedInvestigationInterpreter,
    ConstrainedRoleResponder,
)
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
        self.investigation_interpreter = ConstrainedInvestigationInterpreter(
            llm_provider
        )
        self.assessment_interpreter = ConstrainedAssessmentInterpreter(llm_provider)

    def create_session(
        self, scenario_id: str, variant_id: str, seed: int | None
    ) -> SessionRecord:
        try:
            runtime = self.scenarios.materialize(scenario_id, variant_id)
            scenario_version = self.scenarios.version(scenario_id)
        except (KeyError, ValueError) as exc:
            raise NotFoundError(str(exc)) from exc
        session = self.repo.create(
            scenario_id,
            variant_id,
            scenario_version,
            runtime.to_snapshot(),
            seed,
        )
        self.repo.commit()
        return session

    def get_session(self, session_id: str) -> SessionRecord:
        session = self.repo.get(session_id)
        if session is None:
            raise NotFoundError(f"session not found: {session_id}")
        return session

    def list_sessions(self) -> list[SessionRecord]:
        return self.repo.list_all()

    def start(self, session_id: str) -> SessionRecord:
        session = self.get_session(session_id)
        if session.status != SessionStatus.CREATED:
            raise InvalidOperationError("only a created session can be started")
        scenario = self._runtime_scenario(session)
        session.status = SessionStatus.RUNNING
        self.repo.append_event(
            session.id,
            0,
            EventType.SESSION_STARTED,
            payload={"scenario_version": session.scenario_version},
        )
        for timeline_event in self.timeline_engine.starting_events(scenario.timeline):
            self._trigger_timeline_event(session, timeline_event)
        self.repo.commit()
        return session

    def advance_time(self, session_id: str, minutes: int) -> SessionRecord:
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        old_time = session.simulation_time
        duration = scenario.scenario.duration_minutes
        new_time = min(old_time + minutes, duration)

        due: list[tuple[int, int, object]] = [
            (item.at_minute, 0, item)
            for item in self.timeline_engine.due_events(
                scenario.timeline, old_time, new_time
            )
        ]
        due.extend(
            (run.due_at, 1, run)
            for run in self.investigations(session.id)
            if run.status == InvestigationStatus.IN_PROGRESS
            and old_time < run.due_at <= new_time
        )
        for _, kind, item in sorted(
            due,
            key=lambda entry: (
                entry[0],
                entry[1],
                entry[2].id,
            ),
        ):
            if kind == 0:
                self._trigger_timeline_event(session, item)
            else:
                self._complete_investigation(session, scenario, item)

        session.simulation_time = new_time
        self.repo.append_event(
            session.id,
            new_time,
            EventType.TIME_ADVANCED,
            payload={
                "from_minute": old_time,
                "to_minute": new_time,
                "minutes": new_time - old_time,
            },
        )
        if new_time >= scenario.scenario.duration_minutes:
            session.status = SessionStatus.COMPLETED
            self.repo.append_event(
                session.id,
                new_time,
                EventType.SESSION_COMPLETED,
                payload={"reason": "time_limit"},
            )
        self.repo.commit()
        return session

    def complete(self, session_id: str) -> SessionRecord:
        session = self.get_session(session_id)
        if session.status == SessionStatus.COMPLETED:
            return session
        if session.status != SessionStatus.RUNNING:
            raise InvalidOperationError("session must be running")
        session.status = SessionStatus.COMPLETED
        self.repo.append_event(
            session.id, session.simulation_time, EventType.SESSION_COMPLETED
        )
        self.repo.commit()
        return session

    def role_knowledge(self, session_id: str, role_id: str) -> RoleKnowledge:
        session = self.get_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, role_id)
        events = self.repo.events(session.id, session.simulation_time)
        return self.knowledge_engine.get_role_knowledge(
            scenario, events, role_id, session.simulation_time
        )

    def share_evidence(
        self, session_id: str, from_role: str, to_role: str, evidence_id: str
    ):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, from_role)
        self._require_role(scenario, to_role)
        try:
            scenario.evidence(evidence_id)
        except StopIteration as exc:
            raise NotFoundError(f"evidence not found: {evidence_id}") from exc
        if evidence_id not in self.role_knowledge(session.id, from_role).evidence_ids:
            raise InvalidOperationError(
                f"role {from_role} cannot share evidence it does not know"
            )
        event = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.EVIDENCE_SHARED,
            actor_role=from_role,
            target_role=to_role,
            payload={"evidence_id": evidence_id},
        )
        self.repo.commit()
        return event

    def share_fact(
        self, session_id: str, from_role: str, to_role: str, fact_id: str
    ):
        """Compatibility alias for clients migrating to share-evidence."""
        return self.share_evidence(session_id, from_role, to_role, fact_id)

    async def ask_role(
        self,
        session_id: str,
        target_role: str,
        message: str,
        cited_evidence_ids: list[str] | None = None,
    ):
        return await self._ask_role(
            session_id,
            target_role,
            message,
            cited_evidence_ids or [],
            use_provider_stream=False,
        )

    async def ask_role_stream(
        self,
        session_id: str,
        target_role: str,
        message: str,
        cited_evidence_ids: list[str] | None = None,
    ):
        return await self._ask_role(
            session_id,
            target_role,
            message,
            cited_evidence_ids or [],
            use_provider_stream=True,
        )

    async def _ask_role(
        self,
        session_id: str,
        target_role: str,
        message: str,
        cited_evidence_ids: list[str],
        *,
        use_provider_stream: bool,
    ):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        role = self._require_role(scenario, target_role)
        self._share_external_evidence(
            session,
            scenario,
            cited_evidence_ids,
            [target_role],
            thread_id=f"dm:{target_role}",
        )
        knowledge = self.role_knowledge(session.id, target_role)
        history = self._role_thread_history(session.id, target_role)
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.QUESTION_ASKED,
            target_role=target_role,
            payload={
                "message": message,
                "thread_id": f"dm:{target_role}",
                "cited_evidence_ids": cited_evidence_ids,
            },
        )
        # Persist the trainee's question before inference starts so clients can
        # show it in the thread immediately, even while the reply is still
        # being generated (or if generation later fails).
        self.repo.commit()
        request = RoleResponseRequest(
            role_id=role.id,
            role_display_name=role.display_name,
            responsibilities=role.responsibilities,
            communication_style=role.communication_style,
            personality=role.personality,
            response_guidance=role.response_guidance,
            simulation_time=session.simulation_time,
            permitted_observations=knowledge.observations,
            permitted_findings=knowledge.findings,
            thread_history=history,
            trainee_question=message,
        )
        if use_provider_stream:
            validated = await self.role_responder.generate_streamed(request)
        else:
            validated = await self.role_responder.generate(request)
        self._record_llm_violations(
            session,
            validated.violations,
            target_role=target_role,
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

    def post_message(
        self,
        session_id: str,
        thread_id: str,
        text: str,
        cited_evidence_ids: list[str],
    ):
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        recipients = self._thread_recipients(scenario, thread_id)
        self._share_external_evidence(
            session,
            scenario,
            cited_evidence_ids,
            recipients,
            thread_id=thread_id,
        )
        event = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.MESSAGE_POSTED,
            payload={
                "thread_id": thread_id,
                "text": text,
                "cited_evidence_ids": cited_evidence_ids,
                "sender": "trainee",
            },
        )
        self.repo.commit()
        return event

    def _thread_recipients(
        self,
        scenario: RuntimeScenario,
        thread_id: str,
    ) -> list[str]:
        if thread_id == "channel:bridge":
            return [role.id for role in scenario.roles]
        if thread_id.startswith("dm:"):
            role_id = thread_id.removeprefix("dm:")
            self._require_role(scenario, role_id)
            return [role_id]
        raise InvalidOperationError(f"unknown conversation thread: {thread_id}")

    def _share_external_evidence(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        evidence_ids: list[str],
        recipients: list[str],
        *,
        thread_id: str,
    ) -> None:
        discovered = set().union(
            *(
                self.role_knowledge(session.id, role.id).evidence_ids
                for role in scenario.roles
            )
        )
        unknown = sorted(set(evidence_ids) - discovered)
        if unknown:
            raise InvalidOperationError(
                "cannot cite evidence that has not been discovered: "
                + ", ".join(unknown)
            )
        for role_id in recipients:
            known = self.role_knowledge(session.id, role_id).evidence_ids
            for evidence_id in dict.fromkeys(evidence_ids):
                if evidence_id in known:
                    continue
                self.repo.append_event(
                    session.id,
                    session.simulation_time,
                    EventType.EVIDENCE_SHARED,
                    target_role=role_id,
                    payload={"evidence_id": evidence_id, "thread_id": thread_id},
                )

    def _role_thread_history(
        self,
        session_id: str,
        target_role: str,
    ) -> list[ThreadTurn]:
        turns: list[ThreadTurn] = []
        for event in self.repo.events(session_id):
            if (
                event.event_type == EventType.QUESTION_ASKED
                and event.target_role == target_role
            ):
                turns.append(
                    ThreadTurn(
                        speaker="trainee",
                        text=str(event.payload.get("message", "")),
                        simulation_time=event.simulation_time,
                    )
                )
            elif (
                event.event_type == EventType.ROLE_RESPONDED
                and event.actor_role == target_role
            ):
                turns.append(
                    ThreadTurn(
                        speaker="role",
                        text=str(event.payload.get("message", "")),
                        simulation_time=event.simulation_time,
                    )
                )
        return turns[-6:]

    async def request_investigation(
        self,
        session_id: str,
        requester_role: str,
        performer_role: str,
        request_text: str,
    ) -> InvestigationRequestResult:
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, requester_role)
        self._require_role(scenario, performer_role)
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.INVESTIGATION_REQUESTED,
            actor_role=requester_role,
            target_role=performer_role,
            payload={"request": request_text},
        )

        eligible = self._eligible_investigations(
            session,
            scenario,
            performer_role,
        )
        interpretation_request = InvestigationInterpretationRequest(
            trainee_request=request_text,
            performer_role=performer_role,
            eligible_investigations=[
                EligibleInvestigation(
                    id=item.id,
                    label=item.label,
                    request_description=item.request_description,
                    match_hints=item.match_hints,
                )
                for item in eligible
            ],
        )
        validated = await self.investigation_interpreter.interpret(
            interpretation_request
        )
        self._record_llm_violations(
            session,
            validated.violations,
            target_role=performer_role,
        )
        interpretation = validated.response
        if not interpretation.matched or interpretation.investigation_id is None:
            reason = self._no_investigation_reason(
                session, scenario, performer_role, eligible
            )
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.INVESTIGATION_MATCH_FAILED,
                actor_role=requester_role,
                target_role=performer_role,
                payload={"request": request_text, "reason": reason},
            )
            self.repo.commit()
            return InvestigationRequestResult(
                accepted=False,
                reason=reason,
                suggestions=[
                    {"id": item.id, "label": item.label} for item in eligible
                ],
            )

        eligible_by_id = {item.id: item for item in eligible}
        investigation = eligible_by_id.get(interpretation.investigation_id)
        if investigation is None:
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.INVESTIGATION_REJECTED,
                actor_role=requester_role,
                target_role=performer_role,
                payload={
                    "request": request_text,
                    "reason": "The selected investigation is no longer eligible.",
                },
            )
            self.repo.commit()
            return InvestigationRequestResult(
                accepted=False,
                reason="The selected investigation is no longer eligible.",
            )

        due_at = session.simulation_time + investigation.duration_minutes
        started = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.INVESTIGATION_STARTED,
            actor_role=requester_role,
            target_role=performer_role,
            payload={
                "investigation_id": investigation.id,
                "label": investigation.label,
                "request": request_text,
                "started_at": session.simulation_time,
                "due_at": due_at,
            },
        )
        run = InvestigationRun(
            id=started.id,
            investigation_id=investigation.id,
            label=investigation.label,
            requester_role=requester_role,
            performer_role=performer_role,
            request=request_text,
            status=InvestigationStatus.IN_PROGRESS,
            started_at=session.simulation_time,
            due_at=due_at,
        )
        if due_at == session.simulation_time:
            self._complete_investigation(session, scenario, run)
            run = run.model_copy(
                update={
                    "status": InvestigationStatus.COMPLETED,
                    "completed_at": due_at,
                }
            )
        self.repo.commit()
        return InvestigationRequestResult(
            accepted=True,
            reason="Investigation started.",
            investigation=run,
        )

    def investigations(self, session_id: str) -> list[InvestigationRun]:
        session = self.get_session(session_id)
        scenario = self._runtime_scenario(session)
        events = self.repo.events(session.id)
        completions = {
            event.payload.get("started_event_id"): event
            for event in events
            if event.event_type == EventType.INVESTIGATION_COMPLETED
        }
        runs: list[InvestigationRun] = []
        for event in events:
            if event.event_type != EventType.INVESTIGATION_STARTED:
                continue
            try:
                definition = scenario.investigation(event.payload["investigation_id"])
            except (KeyError, StopIteration):
                continue
            completion = completions.get(event.id)
            runs.append(
                InvestigationRun(
                    id=event.id,
                    investigation_id=definition.id,
                    label=definition.label,
                    requester_role=event.actor_role or "",
                    performer_role=event.target_role or "",
                    request=str(event.payload.get("request", "")),
                    status=(
                        InvestigationStatus.COMPLETED
                        if completion
                        else InvestigationStatus.IN_PROGRESS
                    ),
                    started_at=int(event.payload.get("started_at", event.simulation_time)),
                    due_at=int(event.payload["due_at"]),
                    completed_at=completion.simulation_time if completion else None,
                )
            )
        return runs

    async def record_assessment(
        self,
        session_id: str,
        actor_role: str,
        statement: str,
    ) -> list[AssessmentSnapshot]:
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        self._require_role(scenario, actor_role)
        knowledge = self.role_knowledge(session.id, actor_role)
        request = AssessmentInterpretationRequest(
            trainee_statement=statement,
            actor_role=actor_role,
            hypotheses=scenario.hypotheses,
            known_observations=knowledge.observations,
            known_findings=knowledge.findings,
            confidence_semantics={
                key.value: value for key, value in CONFIDENCE_SEMANTICS.items()
            },
        )
        validated = await self.assessment_interpreter.interpret(request)
        self._record_llm_violations(
            session,
            validated.violations,
            target_role=actor_role,
        )
        recorded: list[AssessmentSnapshot] = []
        for normalized in validated.response.assessments:
            hypothesis = scenario.hypothesis(normalized.hypothesis_id)
            event = self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.ASSESSMENT_RECORDED,
                actor_role=actor_role,
                payload={
                    "hypothesis_id": hypothesis.id,
                    "hypothesis_key": hypothesis.key,
                    "hypothesis_label": hypothesis.label,
                    "confidence": normalized.confidence.value,
                    "basis_evidence_ids": normalized.basis_evidence_ids,
                    "statement": statement,
                },
            )
            recorded.append(
                AssessmentSnapshot(
                    event_id=event.id,
                    hypothesis_id=hypothesis.id,
                    hypothesis_key=hypothesis.key,
                    hypothesis_label=hypothesis.label,
                    actor_role=actor_role,
                    confidence=normalized.confidence,
                    basis_evidence_ids=normalized.basis_evidence_ids,
                    statement=statement,
                    recorded_at=session.simulation_time,
                )
            )
        if not recorded:
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.ASSESSMENT_INTERPRETATION_FAILED,
                actor_role=actor_role,
                payload={
                    "statement": statement,
                    "reason": "No public hypothesis could be mapped reliably.",
                },
            )
        self.repo.commit()
        return recorded

    def assessment_warnings(
        self,
        session_id: str,
        actor_role: str,
        recorded: list[AssessmentSnapshot],
    ) -> list[str]:
        # Non-blocking feedback: flag "confirmed" assessments that no
        # confirmed-reliability evidence supports. The mistake stays the lesson;
        # the trainee just learns about it now instead of at scoring time.
        session = self.get_session(session_id)
        knowledge = self.role_knowledge(session.id, actor_role)
        confirming = {
            item.id
            for item in (*knowledge.observations, *knowledge.findings)
            if item.reliability == Reliability.CONFIRMED
        }
        warnings: list[str] = []
        for snapshot in recorded:
            if snapshot.confidence == Confidence.CONFIRMED and not (
                set(snapshot.basis_evidence_ids) & confirming
            ):
                warnings.append(
                    f"{snapshot.hypothesis_label} was recorded as confirmed, but "
                    "no confirmed-reliability evidence supports that confidence "
                    "level yet."
                )
        return warnings

    def assessments(self, session_id: str) -> AssessmentProjection:
        session = self.get_session(session_id)
        scenario = self._runtime_scenario(session)
        history: list[AssessmentSnapshot] = []
        for event in self.repo.events(session.id):
            if event.event_type != EventType.ASSESSMENT_RECORDED:
                continue
            try:
                hypothesis = scenario.hypothesis(event.payload["hypothesis_id"])
                confidence = Confidence(event.payload["confidence"])
            except (KeyError, StopIteration, ValueError):
                continue
            history.append(
                AssessmentSnapshot(
                    event_id=event.id,
                    hypothesis_id=hypothesis.id,
                    hypothesis_key=hypothesis.key,
                    hypothesis_label=hypothesis.label,
                    actor_role=event.actor_role or "",
                    confidence=confidence,
                    basis_evidence_ids=list(
                        event.payload.get("basis_evidence_ids", [])
                    ),
                    statement=str(event.payload.get("statement", "")),
                    recorded_at=event.simulation_time,
                )
            )
        current_by_hypothesis: dict[str, AssessmentSnapshot] = {}
        for item in history:
            current_by_hypothesis[item.hypothesis_id] = item
        return AssessmentProjection(
            history=history,
            current=list(current_by_hypothesis.values()),
        )

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
        protected = {
            EventType.OBSERVATION_REVEALED,
            EventType.FINDING_REVEALED,
            EventType.EVIDENCE_SHARED,
        }
        return [
            event.model_copy(update={"payload": {"redacted": True}})
            if event.event_type in protected
            else event
            for event in self.repo.events(session_id)
        ]

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

    def external_entities(self, session_id: str):
        session = self.get_session(session_id)
        return self._runtime_scenario(session).external_entities

    def _running_session(self, session_id: str) -> SessionRecord:
        session = self.get_session(session_id)
        if session.status != SessionStatus.RUNNING:
            raise InvalidOperationError("session must be running")
        return session

    def _runtime_scenario(self, session: SessionRecord) -> RuntimeScenario:
        if session.scenario_snapshot is not None:
            return RuntimeScenario.model_validate(session.scenario_snapshot)
        return self.scenarios.materialize(
            session.scenario_id,
            session.variant_id,
            session.scenario_version,
        )

    @staticmethod
    def _require_role(scenario: RuntimeScenario, role_id: str):
        try:
            return scenario.role(role_id)
        except StopIteration as exc:
            raise NotFoundError(f"role not found: {role_id}") from exc

    def _no_investigation_reason(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        performer_role: str,
        eligible,
    ) -> str:
        # Explain *why* nothing matched instead of returning one generic string.
        performable = [
            item
            for item in scenario.investigations
            if performer_role in item.performer_roles
        ]
        if not performable:
            return (
                f"{performer_role} cannot perform any investigation. "
                "Assign the request to a role that can."
            )
        if eligible:
            return (
                "The request did not match a currently available investigation. "
                "Try describing the evidence question more directly."
            )
        known = self.role_knowledge(session.id, performer_role).evidence_ids
        started_ids = {
            event.payload.get("investigation_id")
            for event in self.repo.events(session.id)
            if event.event_type == EventType.INVESTIGATION_STARTED
        }
        missing_evidence: set[str] = set()
        blocked_by_prerequisites = False
        for item in performable:
            if not item.repeatable and item.id in started_ids:
                continue
            prerequisites = item.prerequisites
            missing = set(prerequisites.all_evidence) - known
            any_missing = bool(prerequisites.any_evidence) and not (
                set(prerequisites.any_evidence) & known
            )
            if missing or any_missing:
                blocked_by_prerequisites = True
                missing_evidence |= missing
                if any_missing:
                    missing_evidence |= set(prerequisites.any_evidence) - known
                continue
            if (
                session.simulation_time + item.duration_minutes
                > scenario.scenario.duration_minutes
            ):
                return (
                    "There is not enough exercise time left to complete any "
                    "remaining investigation."
                )
        if blocked_by_prerequisites:
            return (
                "No investigation is available yet: more evidence is needed first"
                + (
                    " (missing "
                    + ", ".join(sorted(missing_evidence))
                    + ")"
                    if missing_evidence
                    else ""
                )
                + ". Ask this role what they know or complete another investigation."
            )
        return "All investigations for this role are already completed."

    def _eligible_investigations(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        performer_role: str,
    ):
        known = self.role_knowledge(session.id, performer_role).evidence_ids
        started_ids = {
            event.payload.get("investigation_id")
            for event in self.repo.events(session.id)
            if event.event_type == EventType.INVESTIGATION_STARTED
        }
        eligible = []
        for item in scenario.investigations:
            prerequisites = item.prerequisites
            if performer_role not in item.performer_roles:
                continue
            if not set(prerequisites.all_evidence).issubset(known):
                continue
            if prerequisites.any_evidence and not (
                set(prerequisites.any_evidence) & known
            ):
                continue
            if not item.repeatable and item.id in started_ids:
                continue
            if (
                session.simulation_time + item.duration_minutes
                > scenario.scenario.duration_minutes
            ):
                continue
            eligible.append(item)
        return eligible

    def _complete_investigation(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        run: InvestigationRun,
    ) -> None:
        self.repo.append_event(
            session.id,
            run.due_at,
            EventType.INVESTIGATION_COMPLETED,
            actor_role=run.requester_role,
            target_role=run.performer_role,
            payload={
                "investigation_id": run.investigation_id,
                "label": run.label,
                "request": run.request,
                "started_event_id": run.id,
                "started_at": run.started_at,
                "due_at": run.due_at,
            },
        )
        outcome = scenario.investigation_outcome(run.investigation_id)
        for finding_id in outcome.reveal_findings:
            self.repo.append_event(
                session.id,
                run.due_at,
                EventType.FINDING_REVEALED,
                actor_role=run.performer_role,
                payload={
                    "finding_id": finding_id,
                    "source": "investigation",
                    "investigation_id": run.investigation_id,
                },
            )

    def _trigger_timeline_event(self, session, timeline_event) -> None:
        self.repo.append_event(
            session.id,
            timeline_event.at_minute,
            EventType.TIMELINE_EVENT_TRIGGERED,
            target_role=timeline_event.role,
            payload={"timeline_event_id": timeline_event.id},
        )
        for observation_id in timeline_event.observation_ids:
            self.repo.append_event(
                session.id,
                timeline_event.at_minute,
                EventType.OBSERVATION_REVEALED,
                actor_role=timeline_event.role,
                payload={
                    "observation_id": observation_id,
                    "source": "timeline",
                    "timeline_event_id": timeline_event.id,
                },
            )

    def _record_llm_violations(
        self,
        session: SessionRecord,
        violations: list[dict[str, object]],
        *,
        target_role: str,
    ) -> None:
        for violation in violations:
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.LLM_POLICY_VIOLATION,
                target_role=target_role,
                payload=violation,
            )
