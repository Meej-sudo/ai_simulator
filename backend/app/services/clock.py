from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import math

from app.models.database import utc_now


@dataclass(frozen=True)
class ClockTick:
    """Elapsed whole simulation minutes plus the sub-minute remainder."""

    captured_at: datetime
    elapsed_minutes: int
    remainder_seconds: float


class ClockService:
    """Convert persisted wall-clock progress into deterministic minute ticks.

    The service deliberately does not mutate a session or execute events. It
    only calculates a tick; SimulationService applies that tick while holding
    the session lock and uses the same advancement pipeline as manual jumps.
    """

    def __init__(self, now: Callable[[], datetime] = utc_now):
        self._now = now

    def now(self) -> datetime:
        return self._as_utc(self._now())

    def tick(
        self,
        last_synced_at: datetime | None,
        remainder_seconds: float,
        *,
        captured_at: datetime | None = None,
    ) -> ClockTick:
        captured = self._as_utc(captured_at or self._now())
        remainder = max(0.0, float(remainder_seconds))
        if last_synced_at is None:
            return ClockTick(captured, 0, remainder % 60.0)

        last_synced = self._as_utc(last_synced_at)
        elapsed_seconds = max(0.0, (captured - last_synced).total_seconds())
        total_seconds = remainder + elapsed_seconds
        elapsed_minutes = math.floor(total_seconds / 60.0)
        return ClockTick(
            captured_at=captured,
            elapsed_minutes=elapsed_minutes,
            remainder_seconds=total_seconds - (elapsed_minutes * 60.0),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        # SQLite can deserialize timezone-aware columns as naive datetimes.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
