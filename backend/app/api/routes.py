import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain.evaluation.engine import EvaluationResult
from app.domain.scenarios.compiler import ScenarioValidationError
from app.domain.simulation.models import (
    AssessmentProjection,
    InvestigationRun,
    StakeholderInteraction,
)
from app.llm.errors import LLMProviderError
from app.schemas.api import (
    ActionAcceptedResponse,
    AdvanceTimeRequest,
    AskRoleRequest,
    AskRoleResponse,
    AssessmentRequest,
    AssessmentSubmissionResponse,
    CreateSessionRequest,
    DecisionCategoryResponse,
    DecisionRequest,
    EventResponse,
    ExternalEntityResponse,
    FindingResponse,
    HypothesisResponse,
    InvestigationRequest,
    InvestigationRequestResponse,
    InteractionRespondRequest,
    KnowledgeResponse,
    LLMConfigurationResponse,
    LLMModelsResponse,
    ObservationResponse,
    PostMessageRequest,
    RoleResponse,
    ScenarioAuthoringResponse,
    ScenarioAuthoringUpdateRequest,
    ScenarioDetailResponse,
    ScenarioSourcesResponse,
    ScenarioSourcesUpdateRequest,
    ScenarioSummaryResponse,
    SessionResponse,
    ShareEvidenceRequest,
    ShareFactRequest,
    UpdateLLMConfigurationRequest,
    VariantResponse,
)
from app.services.errors import InvalidOperationError, NotFoundError
from app.services.simulation import SimulationService


router = APIRouter()


def get_service(request: Request, db: Session = Depends(get_db)) -> SimulationService:
    return SimulationService(db, request.app.state.scenarios, request.app.state.llm_provider)


def call(operation):
    try:
        return operation()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOperationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def call_async(operation):
    try:
        return await operation()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidOperationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def scenario_summary(compiled) -> ScenarioSummaryResponse:
    metadata = compiled.scenario
    return ScenarioSummaryResponse(
        id=metadata.id,
        name=metadata.name,
        description=metadata.description,
        duration_minutes=metadata.duration_minutes,
        variants=[VariantResponse(id=item.id, name=item.name) for item in compiled.variants],
        decision_categories=[
            DecisionCategoryResponse(
                id=item.id,
                display_name=item.display_name,
                description=item.description,
                captures_confidence=item.captures_confidence,
            )
            for item in metadata.decision_categories
        ],
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def llm_configuration_response(request: Request) -> LLMConfigurationResponse:
    configuration = request.app.state.llm_configuration
    return LLMConfigurationResponse(
        provider=configuration.selection.provider,
        model=configuration.selection.model,
        configured=configuration.configured,
        available_providers=list(configuration.available_providers),
    )


@router.get("/settings/llm", response_model=LLMConfigurationResponse)
def get_llm_configuration(request: Request):
    return llm_configuration_response(request)


@router.get("/settings/llm/models", response_model=LLMModelsResponse)
async def get_llm_models(provider: str, request: Request):
    try:
        models = await request.app.state.llm_configuration.models(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LLMModelsResponse(provider=provider, models=models)


@router.put("/settings/llm", response_model=LLMConfigurationResponse)
async def update_llm_configuration(
    body: UpdateLLMConfigurationRequest,
    request: Request,
):
    try:
        await request.app.state.llm_configuration.update(body.provider, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    request.app.state.llm_provider = request.app.state.llm_configuration.provider
    return llm_configuration_response(request)


@router.get("/scenarios", response_model=list[ScenarioSummaryResponse])
def list_scenarios(request: Request):
    return [scenario_summary(item) for item in request.app.state.scenarios.all()]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetailResponse)
def get_scenario(scenario_id: str, request: Request):
    try:
        compiled = request.app.state.scenarios.get(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    summary = scenario_summary(compiled)
    return ScenarioDetailResponse(
        **summary.model_dump(),
        roles=[
            RoleResponse(
                id=role.id,
                display_name=role.display_name,
                responsibilities=role.responsibilities,
                communication_style=role.communication_style,
            )
            for role in compiled.roles
        ],
        external_entities=[
            ExternalEntityResponse.model_validate(entity.model_dump())
            for entity in compiled.external_entities
        ],
        hypotheses=[
            HypothesisResponse.model_validate(item.model_dump())
            for item in compiled.hypotheses
        ],
    )


def scenario_sources_response(
    request: Request, scenario_id: str
) -> ScenarioSourcesResponse:
    registry = request.app.state.scenarios
    try:
        compiled = registry.get(scenario_id)
        files = registry.source_files(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScenarioSourcesResponse(
        scenario=scenario_summary(compiled),
        files=files,
    )


@router.get(
    "/scenarios/{scenario_id}/authoring",
    response_model=ScenarioAuthoringResponse,
)
def get_scenario_authoring(scenario_id: str, request: Request):
    try:
        compiled = request.app.state.scenarios.get(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScenarioAuthoringResponse(
        scenario=scenario_summary(compiled),
        document=compiled,
    )


@router.put(
    "/scenarios/{scenario_id}/authoring",
    response_model=ScenarioAuthoringResponse,
)
def update_scenario_authoring(
    scenario_id: str,
    body: ScenarioAuthoringUpdateRequest,
    request: Request,
):
    try:
        compiled = request.app.state.scenarios.update_document(
            scenario_id, body.document
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScenarioAuthoringResponse(
        scenario=scenario_summary(compiled),
        document=compiled,
    )


@router.get(
    "/scenarios/{scenario_id}/sources",
    response_model=ScenarioSourcesResponse,
)
def get_scenario_sources(scenario_id: str, request: Request):
    return scenario_sources_response(request, scenario_id)


@router.put(
    "/scenarios/{scenario_id}/sources",
    response_model=ScenarioSourcesResponse,
)
def update_scenario_sources(
    scenario_id: str,
    body: ScenarioSourcesUpdateRequest,
    request: Request,
):
    try:
        request.app.state.scenarios.update_source_files(scenario_id, body.files)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return scenario_sources_response(request, scenario_id)


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(
    body: CreateSessionRequest,
    request: Request,
    service: SimulationService = Depends(get_service),
):
    configuration = getattr(request.app.state, "llm_configuration", None)
    if configuration is not None and not configuration.configured:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No AI model is configured. Select a provider and model before "
                "starting an exercise."
            ),
        )
    return call(lambda: service.create_session(body.scenario_id, body.variant_id, body.seed))


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(service: SimulationService = Depends(get_service)):
    return call(service.list_sessions)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.get_session(session_id))


@router.post("/sessions/{session_id}/start", response_model=SessionResponse)
async def start_session(session_id: str, service: SimulationService = Depends(get_service)):
    return await call_async(lambda: service.start_async(session_id))


@router.post("/sessions/{session_id}/advance-time", response_model=SessionResponse)
async def advance_time(
    session_id: str,
    body: AdvanceTimeRequest,
    service: SimulationService = Depends(get_service),
):
    return await call_async(lambda: service.advance_time_async(session_id, body.minutes))


@router.post("/sessions/{session_id}/clock/sync", response_model=SessionResponse)
async def sync_clock(session_id: str, service: SimulationService = Depends(get_service)):
    return await call_async(lambda: service.sync_clock(session_id))


@router.post("/sessions/{session_id}/clock/pause", response_model=SessionResponse)
async def pause_clock(session_id: str, service: SimulationService = Depends(get_service)):
    return await call_async(lambda: service.pause_clock(session_id))


@router.post("/sessions/{session_id}/clock/resume", response_model=SessionResponse)
def resume_clock(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.resume_clock(session_id))


@router.post("/sessions/{session_id}/complete", response_model=SessionResponse)
async def complete_session(
    session_id: str,
    service: SimulationService = Depends(get_service),
):
    return await call_async(lambda: service.complete_async(session_id))


@router.get("/sessions/{session_id}/roles", response_model=list[RoleResponse])
def list_roles(session_id: str, service: SimulationService = Depends(get_service)):
    roles = call(lambda: service.roles(session_id))
    return [
        RoleResponse(
            id=role.id,
            display_name=role.display_name,
            responsibilities=role.responsibilities,
            communication_style=role.communication_style,
        )
        for role in roles
    ]


@router.get(
    "/sessions/{session_id}/external-entities",
    response_model=list[ExternalEntityResponse],
)
def list_external_entities(
    session_id: str, service: SimulationService = Depends(get_service)
):
    entities = call(lambda: service.external_entities(session_id))
    return [
        ExternalEntityResponse.model_validate(entity.model_dump())
        for entity in entities
    ]


@router.get(
    "/sessions/{session_id}/roles/{role_id}/knowledge",
    response_model=KnowledgeResponse,
)
def get_knowledge(
    session_id: str, role_id: str, service: SimulationService = Depends(get_service)
):
    knowledge = call(lambda: service.role_knowledge(session_id, role_id))
    return KnowledgeResponse(
        role_id=knowledge.role_id,
        simulation_time=knowledge.simulation_time,
        observations=[
            ObservationResponse.model_validate(item.model_dump())
            for item in knowledge.observations
        ],
        findings=[
            FindingResponse.model_validate(item.model_dump())
            for item in knowledge.findings
        ],
    )


@router.post("/sessions/{session_id}/ask", response_model=AskRoleResponse)
async def ask_role(
    session_id: str,
    body: AskRoleRequest,
    service: SimulationService = Depends(get_service),
):
    return await call_async(
        lambda: service.ask_role(
            session_id,
            body.target_role,
            body.message,
            body.cited_evidence_ids,
        )
    )


@router.post(
    "/sessions/{session_id}/actions/share-evidence",
    response_model=ActionAcceptedResponse,
)
async def share_evidence(
    session_id: str,
    body: ShareEvidenceRequest,
    service: SimulationService = Depends(get_service),
):
    event = await call_async(
        lambda: service.share_evidence_async(
            session_id,
            body.from_role,
            body.to_role,
            body.evidence_id,
        )
    )
    return ActionAcceptedResponse(
        event_id=event.id,
        simulation_time=event.simulation_time,
    )


def stream_event(event_type: str, **payload) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False) + "\n"


def word_chunks(message: str) -> list[str]:
    # One word plus its trailing whitespace per chunk so the UI can fade each word once.
    return re.findall(r"\S+\s*|\s+", message)


@router.post("/sessions/{session_id}/ask/stream")
async def ask_role_stream(
    session_id: str,
    body: AskRoleRequest,
    service: SimulationService = Depends(get_service),
):
    async def events():
        # Flush headers and let the UI show its warmup cursor before inference.
        yield stream_event("start")
        try:
            response = await service.ask_role_stream(
                session_id,
                body.target_role,
                body.message,
                body.cited_evidence_ids,
            )
        except NotFoundError as exc:
            yield stream_event("error", detail=str(exc), status=404)
            return
        except InvalidOperationError as exc:
            yield stream_event("error", detail=str(exc), status=409)
            return
        except LLMProviderError as exc:
            yield stream_event("error", detail=str(exc), status=502)
            return

        # Provider output is held until fact-boundary validation succeeds, then
        # released one word at a time so unsafe output is never leaked.
        try:
            for chunk in word_chunks(response.message):
                yield stream_event("delta", content=chunk)
                await asyncio.sleep(0.015)
        except Exception as exc:  # noqa: BLE001 - stream must end with a typed error
            yield stream_event(
                "error",
                detail=f"The reply was interrupted: {exc}",
                status=502,
            )
            return

        yield stream_event(
            "complete",
            referenced_evidence_ids=response.referenced_evidence_ids,
            certainty=response.certainty.value,
        )

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/threads/{thread_id:path}/messages",
    response_model=ActionAcceptedResponse,
)
async def post_message(
    session_id: str,
    thread_id: str,
    body: PostMessageRequest,
    service: SimulationService = Depends(get_service),
):
    event = await call_async(
        lambda: service.post_message_async(
            session_id,
            thread_id,
            body.text,
            body.cited_evidence_ids,
        )
    )
    return ActionAcceptedResponse(
        event_id=event.id,
        simulation_time=event.simulation_time,
    )


@router.post(
    "/sessions/{session_id}/actions/share-fact",
    response_model=ActionAcceptedResponse,
    deprecated=True,
)
async def share_fact(
    session_id: str,
    body: ShareFactRequest,
    service: SimulationService = Depends(get_service),
):
    event = await call_async(
        lambda: service.share_evidence_async(
            session_id,
            body.from_role,
            body.to_role,
            body.fact_id,
        )
    )
    return ActionAcceptedResponse(
        event_id=event.id,
        simulation_time=event.simulation_time,
    )


@router.post(
    "/sessions/{session_id}/investigations",
    response_model=InvestigationRequestResponse,
)
async def request_investigation(
    session_id: str,
    body: InvestigationRequest,
    service: SimulationService = Depends(get_service),
):
    return await call_async(
        lambda: service.request_investigation(
            session_id,
            body.requester_role,
            body.performer_role,
            body.request,
        )
    )


@router.get(
    "/sessions/{session_id}/investigations",
    response_model=list[InvestigationRun],
)
def list_investigations(
    session_id: str,
    service: SimulationService = Depends(get_service),
):
    return call(lambda: service.investigations(session_id))


@router.post(
    "/sessions/{session_id}/assessments",
    response_model=AssessmentSubmissionResponse,
)
async def record_assessment(
    session_id: str,
    body: AssessmentRequest,
    service: SimulationService = Depends(get_service),
):
    recorded = await call_async(
        lambda: service.record_assessment(
            session_id,
            body.actor_role,
            body.statement,
        )
    )
    warnings = call(
        lambda: service.assessment_warnings(session_id, body.actor_role, recorded)
    )
    return AssessmentSubmissionResponse(
        recorded=recorded,
        message=(
            "Assessment recorded."
            if recorded
            else "No scenario hypothesis could be identified; the assessment was not recorded."
        ),
        warnings=warnings,
    )


@router.get(
    "/sessions/{session_id}/assessments",
    response_model=AssessmentProjection,
)
def list_assessments(
    session_id: str,
    service: SimulationService = Depends(get_service),
):
    return call(lambda: service.assessments(session_id))


@router.post(
    "/sessions/{session_id}/actions/decision",
    response_model=ActionAcceptedResponse,
)
async def make_decision(
    session_id: str,
    body: DecisionRequest,
    service: SimulationService = Depends(get_service),
):
    event = await call_async(
        lambda: service.make_decision_async(
            session_id,
            body.actor_role,
            body.category,
            body.decision,
            body.confidence,
            body.rationale,
        )
    )
    return ActionAcceptedResponse(
        event_id=event.id,
        simulation_time=event.simulation_time,
    )


@router.get(
    "/sessions/{session_id}/interactions",
    response_model=list[StakeholderInteraction],
)
def list_interactions(
    session_id: str,
    service: SimulationService = Depends(get_service),
):
    return call(lambda: service.interactions(session_id))


@router.post(
    "/sessions/{session_id}/interactions/{interaction_id}/respond",
    response_model=StakeholderInteraction,
)
async def respond_to_interaction(
    session_id: str,
    interaction_id: str,
    body: InteractionRespondRequest,
    service: SimulationService = Depends(get_service),
):
    return await call_async(
        lambda: service.respond_to_interaction(
            session_id,
            interaction_id,
            body.message,
        )
    )


@router.get("/sessions/{session_id}/events", response_model=list[EventResponse])
def get_events(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.events(session_id))


@router.get("/sessions/{session_id}/evaluation", response_model=EvaluationResult)
def get_evaluation(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.evaluation(session_id))
