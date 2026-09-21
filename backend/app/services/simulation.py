from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.evaluation.engine import EvaluationEngine, EvaluationResult
from app.domain.knowledge.engine import KnowledgeEngine, RoleKnowledge
from app.domain.scenarios.models import (
    CONFIDENCE_SEMANTICS,
    AllTrigger,
    AnyTrigger,
    AssessmentExistsTrigger,
    Confidence,
    OrganizationalPressureEventDefinition,
    Reliability,
    RevealEvidenceEventDefinition,
    RevealFindingEffect,
    RevealObservationEffect,
    RuntimeScenario,
    StakeholderInteractionEventDefinition,
)
from app.domain.simulation.models import (
    AssessmentProjection,
    AssessmentSnapshot,
    EventSnapshot,
    EventType,
    InvestigationRequestResult,
    InvestigationRun,
    InteractionMessage,
    InteractionResponse,
    InteractionStatus,
    InvestigationStatus,
    SessionStatus,
    StakeholderInteraction,
)
from app.domain.simulation.event_engine import EventEngine, SessionState
from app.llm.base import LLMProvider
from app.llm.models import (
    AssessmentInterpretationRequest,
    EligibleInvestigation,
    InvestigationInterpretationRequest,
    RoleResponseRequest,
    StakeholderAssessmentContext,
    StakeholderMessageRequest,
    ThreadTurn,
)
from app.llm.validation import (
    ConstrainedAssessmentInterpreter,
    ConstrainedInvestigationInterpreter,
    ConstrainedRoleResponder,
)
from app.models.database import SessionRecord
from app.repositories.sessions import SessionRepository
from app.services.clock import ClockService
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.scenario_registry import ScenarioRegistry


class SimulationService:
    def __init__(
        self,
        db: Session,
        scenarios: ScenarioRegistry,
        llm_provider: LLMProvider,
        clock: ClockService | None = None,
    ):
        self.repo = SessionRepository(db)
        self.scenarios = scenarios
        self.clock = clock or ClockService()
        self.knowledge_engine = KnowledgeEngine()
        self.event_engine = EventEngine()
        self.evaluation_engine = EvaluationEngine()
        self.llm_provider = llm_provider
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
        """Start a session and execute deterministic non-LLM reveal events.

        The sync entry point remains for service-level compatibility. API callers
        use start_async so stakeholder events can also generate wording.
        """
        session = self.get_session(session_id)
        if session.status != SessionStatus.CREATED:
            raise InvalidOperationError("only a created session can be started")
        scenario = self._runtime_scenario(session)
        session.status = SessionStatus.RUNNING
        session.clock_running = True
        session.clock_last_synced_at = self.clock.now()
        session.clock_remainder_seconds = 0.0
        self.repo.append_event(
            session.id,
            0,
            EventType.SESSION_STARTED,
            payload={"scenario_version": session.scenario_version},
        )
        self._process_reveal_events(session, scenario)
        self.repo.commit()
        return session

    async def start_async(self, session_id: str) -> SessionRecord:
        session = self.start(session_id)
        await self._process_authored_events(session, self._runtime_scenario(session))
        self.repo.commit()
        return session

    def advance_time(self, session_id: str, minutes: int) -> SessionRecord:
        """Advance time while preserving the original synchronous service API."""
        session = self._running_session(session_id)
        session.clock_last_synced_at = self.clock.now()
        scenario = self._runtime_scenario(session)
        old_time = session.simulation_time
        duration = scenario.scenario.duration_minutes
        new_time = min(old_time + minutes, duration)

        investigation_runs = [
            run
            for run in self.investigations(session.id)
            if run.status == InvestigationStatus.IN_PROGRESS
            and old_time < run.due_at <= new_time
        ]
        checkpoints = set(
            self.event_engine.time_checkpoints(scenario.events, old_time, new_time)
        )
        checkpoints.update(run.due_at for run in investigation_runs)
        for checkpoint in sorted(checkpoints):
            session.simulation_time = checkpoint
            self._process_reveal_events(session, scenario)
            for run in sorted(
                (item for item in investigation_runs if item.due_at == checkpoint),
                key=lambda item: item.id,
            ):
                self._complete_investigation(session, scenario, run)
            self._process_reveal_events(session, scenario)

        session.simulation_time = new_time
        self._process_reveal_events(session, scenario)
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
        if new_time >= duration:
            session.status = SessionStatus.COMPLETED
            session.clock_running = False
            session.clock_remainder_seconds = 0.0
            self.repo.append_event(
                session.id,
                new_time,
                EventType.SESSION_COMPLETED,
                payload={"reason": "time_limit"},
            )
        self.repo.commit()
        return session

    async def advance_time_async(self, session_id: str, minutes: int) -> SessionRecord:
        """Apply elapsed real time first, then the requested manual jump."""
        session = self._running_session_for_update(session_id)
        captured_at = self.clock.now()
        await self._sync_clock_locked(session, captured_at=captured_at)
        if session.status == SessionStatus.RUNNING:
            await self._advance_time_locked_async(
                session,
                minutes,
                source="manual",
            )
        self.repo.commit()
        return session

    async def sync_clock(self, session_id: str) -> SessionRecord:
        """Persist elapsed wall time and process each crossed minute exactly once."""
        session = self._session_for_update(session_id)
        if session.status == SessionStatus.CREATED:
            raise InvalidOperationError("session must be running")
        if session.status == SessionStatus.COMPLETED:
            session.clock_running = False
            self.repo.commit()
            return session
        await self._sync_clock_locked(session, captured_at=self.clock.now())
        self.repo.commit()
        return session

    async def pause_clock(self, session_id: str) -> SessionRecord:
        session = self._running_session_for_update(session_id)
        if not session.clock_running:
            self.repo.commit()
            return session

        await self._sync_clock_locked(session, captured_at=self.clock.now())
        if session.status == SessionStatus.RUNNING:
            session.clock_running = False
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.CLOCK_PAUSED,
                payload={"remainder_seconds": session.clock_remainder_seconds},
            )
        self.repo.commit()
        return session

    def resume_clock(self, session_id: str) -> SessionRecord:
        session = self._running_session_for_update(session_id)
        if session.clock_running:
            self.repo.commit()
            return session

        session.clock_running = True
        session.clock_last_synced_at = self.clock.now()
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.CLOCK_RESUMED,
            payload={"remainder_seconds": session.clock_remainder_seconds},
        )
        self.repo.commit()
        return session

    async def complete_async(self, session_id: str) -> SessionRecord:
        session = self._session_for_update(session_id)
        if session.status == SessionStatus.COMPLETED:
            session.clock_running = False
            self.repo.commit()
            return session
        if session.status != SessionStatus.RUNNING:
            raise InvalidOperationError("session must be running")

        await self._sync_clock_locked(session, captured_at=self.clock.now())
        if session.status == SessionStatus.RUNNING:
            session.status = SessionStatus.COMPLETED
            session.clock_running = False
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.SESSION_COMPLETED,
                payload={"reason": "trainee_ended"},
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
        session.clock_running = False
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
        self._process_reveal_events(session, scenario)
        self.repo.commit()
        return event

    async def share_evidence_async(
        self, session_id: str, from_role: str, to_role: str, evidence_id: str
    ):
        event = self.share_evidence(session_id, from_role, to_role, evidence_id)
        session = self.get_session(session_id)
        await self._process_authored_events(session, self._runtime_scenario(session))
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
        await self._process_authored_events(session, scenario)
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
        self._process_reveal_events(session, scenario)
        self.repo.commit()
        return event

    async def post_message_async(
        self,
        session_id: str,
        thread_id: str,
        text: str,
        cited_evidence_ids: list[str],
    ):
        event = self.post_message(session_id, thread_id, text, cited_evidence_ids)
        session = self.get_session(session_id)
        await self._process_authored_events(session, self._runtime_scenario(session))
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
        await self._process_authored_events(session, scenario)
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
        await self._process_authored_events(session, scenario)
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
        self._process_reveal_events(session, scenario)
        self.repo.commit()
        return event

    async def make_decision_async(
        self,
        session_id: str,
        actor_role: str,
        category: str,
        decision: str,
        confidence: Confidence | None,
        rationale: str | None,
    ):
        event = self.make_decision(
            session_id, actor_role, category, decision, confidence, rationale
        )
        session = self.get_session(session_id)
        await self._process_authored_events(session, self._runtime_scenario(session))
        self.repo.commit()
        return event

    def interactions(self, session_id: str) -> list[StakeholderInteraction]:
        session = self.get_session(session_id)
        scenario = self._runtime_scenario(session)
        projected: dict[str, StakeholderInteraction] = {}
        for event in self.repo.events(session.id):
            interaction_id = str(event.payload.get("interaction_id", ""))
            if event.event_type == EventType.STAKEHOLDER_INTERACTION_STARTED:
                if not interaction_id:
                    continue
                role_id = event.actor_role or ""
                try:
                    display_name = scenario.role(role_id).display_name
                except StopIteration:
                    display_name = role_id
                projected[interaction_id] = StakeholderInteraction(
                    id=interaction_id,
                    event_definition_id=str(
                        event.payload.get("event_definition_id", "")
                    ),
                    actor_role=role_id,
                    actor_display_name=display_name,
                    started_at=event.simulation_time,
                    status=InteractionStatus.WAITING_FOR_TRAINEE,
                    messages=[],
                    responses=[],
                )
                continue
            interaction = projected.get(interaction_id)
            if interaction is None:
                continue
            if event.event_type in {
                EventType.STAKEHOLDER_MESSAGE_CREATED,
                EventType.STAKEHOLDER_FOLLOWUP_CREATED,
            }:
                interaction.messages.append(
                    InteractionMessage(
                        id=event.id,
                        kind=(
                            "follow_up"
                            if event.event_type == EventType.STAKEHOLDER_FOLLOWUP_CREATED
                            else "stakeholder"
                        ),
                        message=str(event.payload.get("message", "")),
                        simulation_time=event.simulation_time,
                    )
                )
                interaction.status = InteractionStatus.WAITING_FOR_TRAINEE
            elif event.event_type == EventType.TRAINEE_STAKEHOLDER_RESPONSE:
                interaction.responses.append(
                    InteractionResponse(
                        id=event.id,
                        message=str(event.payload.get("message", "")),
                        simulation_time=event.simulation_time,
                    )
                )
                interaction.status = InteractionStatus.RESPONDED
            elif event.event_type == EventType.STAKEHOLDER_INTERACTION_RESOLVED:
                interaction.status = InteractionStatus.RESOLVED
        return list(projected.values())

    async def respond_to_interaction(
        self,
        session_id: str,
        interaction_id: str,
        message: str,
    ) -> StakeholderInteraction:
        session = self._running_session(session_id)
        scenario = self._runtime_scenario(session)
        interaction = next(
            (item for item in self.interactions(session_id) if item.id == interaction_id),
            None,
        )
        if interaction is None:
            raise NotFoundError(f"interaction not found: {interaction_id}")
        if interaction.status != InteractionStatus.WAITING_FOR_TRAINEE:
            raise InvalidOperationError("interaction is not waiting for a trainee response")
        try:
            definition = next(
                item
                for item in scenario.events
                if item.id == interaction.event_definition_id
                and isinstance(item, StakeholderInteractionEventDefinition)
            )
        except StopIteration as exc:
            raise InvalidOperationError(
                "interaction definition is unavailable in this session snapshot"
            ) from exc

        actor_knowledge = self.role_knowledge(session.id, definition.actor_role)
        discovered = sorted(
            set().union(
                *(
                    self.role_knowledge(session.id, role.id).evidence_ids
                    for role in scenario.roles
                )
            )
        )
        current_assessments = self.assessments(session.id).current
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.TRAINEE_STAKEHOLDER_RESPONSE,
            target_role=definition.actor_role,
            payload={
                "interaction_id": interaction_id,
                "message": message,
                "actor": "trainee",
                "target_role": definition.actor_role,
                "knowledge_snapshot": {
                    "stakeholder_role": definition.actor_role,
                    "stakeholder_evidence_ids": sorted(actor_knowledge.evidence_ids),
                    "trainee_discovered_evidence_ids": discovered,
                },
                "current_assessments": [
                    item.model_dump(mode="json") for item in current_assessments
                ],
            },
        )

        follow_up = self._required_follow_up(
            definition,
            interaction_id,
            message,
            set(discovered),
            self.repo.events(session.id),
        )
        if follow_up is not None:
            request = self._stakeholder_message_request(
                session,
                scenario,
                definition,
                follow_up.objective,
                follow_up.context,
            )
            generated = await self.llm_provider.generate_stakeholder_message(request)
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.STAKEHOLDER_FOLLOWUP_CREATED,
                actor_role=definition.actor_role,
                payload={
                    "interaction_id": interaction_id,
                    "follow_up_id": follow_up.id,
                    "message": generated.message,
                },
            )
        else:
            self.repo.append_event(
                session.id,
                session.simulation_time,
                EventType.STAKEHOLDER_INTERACTION_RESOLVED,
                actor_role=definition.actor_role,
                payload={"interaction_id": interaction_id},
            )
        await self._process_authored_events(session, scenario)
        self.repo.commit()
        return next(
            item for item in self.interactions(session_id) if item.id == interaction_id
        )

    @staticmethod
    def _response_confidence(message: str) -> Confidence:
        value = message.casefold()
        negative_confirmation = any(
            phrase in value
            for phrase in (
                "not confirmed",
                "isn't confirmed",
                "is not confirmed",
                "unconfirmed",
                "no confirmation",
            )
        )
        if negative_confirmation:
            if any(phrase in value for phrase in ("strongly suspect", "high confidence", "highly likely", "very likely")):
                return Confidence.HIGH
            if any(phrase in value for phrase in ("suspect", "likely", "possible", "may have")):
                return Confidence.MEDIUM
            return Confidence.LOW
        if any(word in value for word in ("confirmed", "certain", "definitely", "proven")):
            return Confidence.CONFIRMED
        if any(phrase in value for phrase in ("strongly suspect", "high confidence", "highly likely", "very likely")):
            return Confidence.HIGH
        if any(phrase in value for phrase in ("suspect", "likely", "possible", "may have")):
            return Confidence.MEDIUM
        return Confidence.LOW

    def _required_follow_up(
        self,
        definition: StakeholderInteractionEventDefinition,
        interaction_id: str,
        message: str,
        discovered_evidence: set[str],
        events: list[EventSnapshot],
    ):
        already_created = {
            str(event.payload.get("follow_up_id"))
            for event in events
            if event.event_type == EventType.STAKEHOLDER_FOLLOWUP_CREATED
            and event.payload.get("interaction_id") == interaction_id
        }
        rank = {
            Confidence.LOW: 0,
            Confidence.MEDIUM: 1,
            Confidence.HIGH: 2,
            Confidence.CONFIRMED: 3,
        }
        response_confidence = self._response_confidence(message)
        for follow_up in definition.follow_ups:
            if follow_up.id in already_created:
                continue
            condition = follow_up.when
            claimed = condition.trainee_assessment.confidence
            if rank[response_confidence] < rank[claimed]:
                continue
            confirmation_known = bool(
                discovered_evidence
                & set(condition.evidence_support.confirmation_evidence_ids)
            )
            support = Confidence.CONFIRMED if confirmation_known else Confidence.LOW
            if rank[support] < rank[condition.evidence_support.below]:
                return follow_up
        return None

    def events(self, session_id: str) -> list[EventSnapshot]:
        self.get_session(session_id)
        protected = {
            EventType.OBSERVATION_REVEALED,
            EventType.FINDING_REVEALED,
            EventType.EVIDENCE_SHARED,
            EventType.EVENT_DEFINITION_FIRED,
            EventType.STAKEHOLDER_INTERACTION_STARTED,
            EventType.TRAINEE_STAKEHOLDER_RESPONSE,
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

    def _session_for_update(self, session_id: str) -> SessionRecord:
        session = self.repo.get_for_update(session_id)
        if session is None:
            raise NotFoundError(f"session not found: {session_id}")
        return session

    def _running_session_for_update(self, session_id: str) -> SessionRecord:
        session = self._session_for_update(session_id)
        if session.status != SessionStatus.RUNNING:
            raise InvalidOperationError("session must be running")
        return session

    async def _sync_clock_locked(
        self,
        session: SessionRecord,
        *,
        captured_at: datetime,
    ) -> None:
        if not session.clock_running or session.status != SessionStatus.RUNNING:
            return

        tick = self.clock.tick(
            session.clock_last_synced_at,
            session.clock_remainder_seconds,
            captured_at=captured_at,
        )
        session.clock_last_synced_at = tick.captured_at
        session.clock_remainder_seconds = tick.remainder_seconds
        if tick.elapsed_minutes:
            await self._advance_time_locked_async(
                session,
                tick.elapsed_minutes,
                source="clock",
            )

    async def _advance_time_locked_async(
        self,
        session: SessionRecord,
        minutes: int,
        *,
        source: str,
    ) -> None:
        """Advance through ordered minute checkpoints in the current transaction."""
        if minutes <= 0:
            return

        scenario = self._runtime_scenario(session)
        old_time = session.simulation_time
        duration = scenario.scenario.duration_minutes
        new_time = min(old_time + minutes, duration)
        investigation_runs = [
            run
            for run in self.investigations(session.id)
            if run.status == InvestigationStatus.IN_PROGRESS
            and old_time < run.due_at <= new_time
        ]
        checkpoints = set(
            self.event_engine.time_checkpoints(scenario.events, old_time, new_time)
        )
        checkpoints.update(run.due_at for run in investigation_runs)
        checkpoints.add(new_time)

        for checkpoint in sorted(checkpoints):
            session.simulation_time = checkpoint
            # Authored evidence follows scenario order. Investigation runs are
            # projected in their original event sequence, so simultaneous work
            # completes in request order rather than random UUID order.
            self._process_reveal_events(session, scenario)
            for run in (
                item for item in investigation_runs if item.due_at == checkpoint
            ):
                self._complete_investigation(session, scenario, run)
            self._process_reveal_events(session, scenario)
            await self._process_authored_events(session, scenario)

        self.repo.append_event(
            session.id,
            new_time,
            EventType.TIME_ADVANCED,
            payload={
                "from_minute": old_time,
                "to_minute": new_time,
                "minutes": new_time - old_time,
                "source": source,
            },
        )
        if new_time >= duration:
            session.status = SessionStatus.COMPLETED
            session.clock_running = False
            session.clock_remainder_seconds = 0.0
            self.repo.append_event(
                session.id,
                new_time,
                EventType.SESSION_COMPLETED,
                payload={"reason": "time_limit"},
            )

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

    def _event_state(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        fired_in_cycle: set[str] | None = None,
    ) -> SessionState:
        return SessionState(
            simulation_time=session.simulation_time,
            events=self.repo.events(session.id, session.simulation_time),
            evidence_by_role={
                role.id: self.role_knowledge(session.id, role.id).evidence_ids
                for role in scenario.roles
            },
            fired_in_cycle=fired_in_cycle or set(),
        )

    def _process_reveal_events(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
    ) -> None:
        fired_in_cycle: set[str] = set()
        while True:
            eligible = [
                definition
                for definition in self.event_engine.evaluate(
                    scenario,
                    self._event_state(session, scenario, fired_in_cycle),
                )
                if isinstance(definition, RevealEvidenceEventDefinition)
            ]
            if not eligible:
                return
            for definition in eligible:
                self._execute_reveal_event(session, definition)
                fired_in_cycle.add(definition.id)

    async def _process_authored_events(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
    ) -> None:
        fired_in_cycle: set[str] = set()
        while True:
            eligible = self.event_engine.evaluate(
                scenario,
                self._event_state(session, scenario, fired_in_cycle),
            )
            if not eligible:
                return
            for definition in eligible:
                if isinstance(definition, RevealEvidenceEventDefinition):
                    self._execute_reveal_event(session, definition)
                elif isinstance(definition, OrganizationalPressureEventDefinition):
                    self._execute_organizational_pressure(session, scenario, definition)
                elif isinstance(definition, StakeholderInteractionEventDefinition):
                    await self._execute_stakeholder_interaction(
                        session, scenario, definition
                    )
                fired_in_cycle.add(definition.id)

    def _execute_reveal_event(
        self,
        session: SessionRecord,
        definition: RevealEvidenceEventDefinition,
    ) -> None:
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.EVENT_DEFINITION_FIRED,
            payload={
                "event_definition_id": definition.id,
                "event_definition_type": definition.type,
            },
        )
        target_roles = {effect.role_id for effect in definition.effects}
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.TIMELINE_EVENT_TRIGGERED,
            target_role=next(iter(target_roles)) if len(target_roles) == 1 else None,
            payload={
                "timeline_event_id": definition.id,
                "event_definition_id": definition.id,
            },
        )
        for effect in definition.effects:
            if isinstance(effect, RevealObservationEffect):
                event_type = EventType.OBSERVATION_REVEALED
                payload = {
                    "observation_id": effect.observation_id,
                    "source": "authored_event",
                    "event_definition_id": definition.id,
                }
            elif isinstance(effect, RevealFindingEffect):
                event_type = EventType.FINDING_REVEALED
                payload = {
                    "finding_id": effect.finding_id,
                    "source": "authored_event",
                    "event_definition_id": definition.id,
                }
            else:
                continue
            self.repo.append_event(
                session.id,
                session.simulation_time,
                event_type,
                actor_role=effect.role_id,
                payload=payload,
            )

    def _execute_organizational_pressure(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        definition: OrganizationalPressureEventDefinition,
    ) -> None:
        if definition.source.kind == "role":
            source = self._require_role(scenario, definition.source.id)
            actor_role = source.id
            source_type = "internal_role"
        else:
            try:
                source = scenario.external_entity(definition.source.id)
            except StopIteration as exc:
                raise NotFoundError(
                    f"external entity not found: {definition.source.id}"
                ) from exc
            actor_role = None
            source_type = source.type

        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.EVENT_DEFINITION_FIRED,
            actor_role=actor_role,
            payload={
                "event_definition_id": definition.id,
                "event_definition_type": definition.type,
                "source_kind": definition.source.kind,
                "source_id": source.id,
            },
        )
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.ORGANIZATIONAL_PRESSURE_APPLIED,
            actor_role=actor_role,
            payload={
                "event_definition_id": definition.id,
                "source_kind": definition.source.kind,
                "source_id": source.id,
                "source_display_name": source.display_name,
                "source_type": source_type,
                "category": definition.pressure.category,
                "severity": definition.pressure.severity,
                "message": definition.pressure.message,
            },
        )

    async def _execute_stakeholder_interaction(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        definition: StakeholderInteractionEventDefinition,
    ) -> None:
        role = self._require_role(scenario, definition.actor_role)
        request = self._stakeholder_message_request(
            session,
            scenario,
            definition,
            definition.interaction.objective,
            definition.interaction.context,
        )
        response = await self.llm_provider.generate_stakeholder_message(request)
        fired = self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.EVENT_DEFINITION_FIRED,
            actor_role=definition.actor_role,
            payload={
                "event_definition_id": definition.id,
                "event_definition_type": definition.type,
            },
        )
        interaction_id = fired.id
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.STAKEHOLDER_INTERACTION_STARTED,
            actor_role=definition.actor_role,
            payload={
                "interaction_id": interaction_id,
                "event_definition_id": definition.id,
                "target": "trainee",
            },
        )
        self.repo.append_event(
            session.id,
            session.simulation_time,
            EventType.STAKEHOLDER_MESSAGE_CREATED,
            actor_role=definition.actor_role,
            payload={
                "interaction_id": interaction_id,
                "message": response.message,
                "actor_display_name": role.display_name,
            },
        )

    def _stakeholder_message_request(
        self,
        session: SessionRecord,
        scenario: RuntimeScenario,
        definition: StakeholderInteractionEventDefinition,
        objective: str,
        context: list[str],
    ) -> StakeholderMessageRequest:
        role = self._require_role(scenario, definition.actor_role)
        knowledge = self.role_knowledge(session.id, role.id)
        relevant_ids = self._assessment_ids_for_trigger(definition.trigger)
        assessments = [
            item
            for item in self.assessments(session.id).current
            if not relevant_ids or item.hypothesis_id in relevant_ids
        ]
        return StakeholderMessageRequest(
            role_id=role.id,
            role_display_name=role.display_name,
            responsibilities=role.responsibilities,
            communication_style=role.communication_style,
            personality=role.personality,
            response_guidance=role.response_guidance,
            objective=objective,
            context=context,
            permitted_observations=knowledge.observations,
            permitted_findings=knowledge.findings,
            relevant_assessments=[
                StakeholderAssessmentContext(
                    hypothesis_id=item.hypothesis_id,
                    hypothesis_label=item.hypothesis_label,
                    confidence=item.confidence,
                    statement=item.statement,
                )
                for item in assessments
            ],
        )

    @classmethod
    def _assessment_ids_for_trigger(cls, trigger) -> set[str]:
        if isinstance(trigger, AssessmentExistsTrigger):
            return {trigger.hypothesis_id}
        if isinstance(trigger, (AllTrigger, AnyTrigger)):
            return set().union(
                *(cls._assessment_ids_for_trigger(item) for item in trigger.triggers)
            )
        return set()

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
