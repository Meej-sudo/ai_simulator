from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.simulation.models import EventSnapshot, EventType, SessionStatus
from app.models.database import EventRecord, SessionRecord


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        scenario_id: str,
        variant_id: str,
        scenario_version: str,
        scenario_snapshot: dict[str, Any],
        seed: int | None,
    ) -> SessionRecord:
        record = SessionRecord(
            scenario_id=scenario_id,
            variant_id=variant_id,
            scenario_version=scenario_version,
            scenario_snapshot=scenario_snapshot,
            seed=seed,
            status=SessionStatus.CREATED,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        return self.db.get(SessionRecord, session_id)

    def append_event(
        self,
        session_id: str,
        simulation_time: int,
        event_type: EventType,
        *,
        actor_role: str | None = None,
        target_role: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventRecord:
        last_sequence = self.db.scalar(
            select(func.max(EventRecord.sequence)).where(EventRecord.session_id == session_id)
        )
        event = EventRecord(
            session_id=session_id,
            sequence=(last_sequence or 0) + 1,
            simulation_time=simulation_time,
            event_type=event_type,
            actor_role=actor_role,
            target_role=target_role,
            payload=payload or {},
        )
        self.db.add(event)
        self.db.flush()
        return event

    def events(self, session_id: str, through_time: int | None = None) -> list[EventSnapshot]:
        statement = select(EventRecord).where(EventRecord.session_id == session_id)
        if through_time is not None:
            statement = statement.where(EventRecord.simulation_time <= through_time)
        records = self.db.scalars(statement.order_by(EventRecord.sequence)).all()
        return [EventSnapshot.model_validate(item) for item in records]

    def commit(self) -> None:
        self.db.commit()
