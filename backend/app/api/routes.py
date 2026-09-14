from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain.evaluation.engine import EvaluationResult
from app.schemas.api import (
    ActionAcceptedResponse,
    AdvanceTimeRequest,
    AskRoleRequest,
    AskRoleResponse,
    CreateSessionRequest,
    DecisionCategoryResponse,
    DecisionRequest,
    EventResponse,
    FactResponse,
    KnowledgeResponse,
    RoleResponse,
    ScenarioDetailResponse,
    ScenarioSummaryResponse,
    SessionResponse,
    ShareFactRequest,
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
    )


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(body: CreateSessionRequest, service: SimulationService = Depends(get_service)):
    return call(lambda: service.create_session(body.scenario_id, body.variant_id, body.seed))


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.get_session(session_id))


@router.post("/sessions/{session_id}/start", response_model=SessionResponse)
def start_session(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.start(session_id))


@router.post("/sessions/{session_id}/advance-time", response_model=SessionResponse)
def advance_time(
    session_id: str,
    body: AdvanceTimeRequest,
    service: SimulationService = Depends(get_service),
):
    return call(lambda: service.advance_time(session_id, body.minutes))


@router.post("/sessions/{session_id}/complete", response_model=SessionResponse)
def complete_session(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.complete(session_id))


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
    "/sessions/{session_id}/roles/{role_id}/knowledge",
    response_model=KnowledgeResponse,
)
def get_knowledge(
    session_id: str, role_id: str, service: SimulationService = Depends(get_service)
):
    session = call(lambda: service.get_session(session_id))
    facts = call(lambda: service.role_knowledge(session_id, role_id))
    return KnowledgeResponse(
        role_id=role_id,
        simulation_time=session.simulation_time,
        facts=[FactResponse.model_validate(fact.model_dump()) for fact in facts],
    )


@router.post("/sessions/{session_id}/ask", response_model=AskRoleResponse)
async def ask_role(
    session_id: str,
    body: AskRoleRequest,
    service: SimulationService = Depends(get_service),
):
    return await call_async(lambda: service.ask_role(session_id, body.target_role, body.message))


@router.post(
    "/sessions/{session_id}/actions/share-fact",
    response_model=ActionAcceptedResponse,
)
def share_fact(
    session_id: str,
    body: ShareFactRequest,
    service: SimulationService = Depends(get_service),
):
    event = call(
        lambda: service.share_fact(session_id, body.from_role, body.to_role, body.fact_id)
    )
    return ActionAcceptedResponse(event_id=event.id, simulation_time=event.simulation_time)


@router.post(
    "/sessions/{session_id}/actions/decision",
    response_model=ActionAcceptedResponse,
)
def make_decision(
    session_id: str,
    body: DecisionRequest,
    service: SimulationService = Depends(get_service),
):
    event = call(
        lambda: service.make_decision(
            session_id,
            body.actor_role,
            body.category,
            body.decision,
            body.confidence,
            body.rationale,
        )
    )
    return ActionAcceptedResponse(event_id=event.id, simulation_time=event.simulation_time)


@router.get("/sessions/{session_id}/events", response_model=list[EventResponse])
def get_events(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.events(session_id))


@router.get("/sessions/{session_id}/evaluation", response_model=EvaluationResult)
def get_evaluation(session_id: str, service: SimulationService = Depends(get_service)):
    return call(lambda: service.evaluation(session_id))
