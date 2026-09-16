from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain.simulation.models import EventType
from app.models.database import Base
from app.repositories.sessions import SessionRepository


def test_concurrent_events_receive_contiguous_sequences(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'events.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        repo = SessionRepository(db)
        session = repo.create(
            "scenario",
            "variant",
            "version",
            {"scenario": {}, "variant_id": "variant"},
            seed=1,
        )
        repo.commit()
        session_id = session.id

    workers = 12
    barrier = Barrier(workers)

    def append_event(worker: int) -> None:
        with Session(engine) as db:
            barrier.wait()
            repo = SessionRepository(db)
            repo.append_event(
                session_id,
                simulation_time=worker,
                event_type=EventType.TIME_ADVANCED,
                payload={"worker": worker},
            )
            repo.commit()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(append_event, range(workers)))

    with Session(engine) as db:
        events = SessionRepository(db).events(session_id)

    assert [event.sequence for event in events] == list(range(1, workers + 1))
    assert {event.payload["worker"] for event in events} == set(range(workers))
