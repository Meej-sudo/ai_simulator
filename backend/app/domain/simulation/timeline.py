from app.domain.scenarios.models import TimelineEvent


class TimelineEngine:
    @staticmethod
    def due_events(
        events: list[TimelineEvent], current_time: int, new_time: int
    ) -> list[TimelineEvent]:
        if new_time < current_time:
            raise ValueError("simulation time cannot move backwards")
        return sorted(
            (
                event
                for event in events
                if current_time < event.at_minute <= new_time
            ),
            key=lambda event: (event.at_minute, event.id),
        )

    @staticmethod
    def starting_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
        return sorted(
            (event for event in events if event.at_minute == 0),
            key=lambda event: event.id,
        )
