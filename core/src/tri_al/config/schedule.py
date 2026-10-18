"""``update.schedule``: when the worker starts an update by itself (docs/design.md §5.4).

The forms are ``off``, ``hourly``, ``daily``, ``weekly``, ``daily at HH:MM`` (local time)
and ``every N minutes|hours|days``. A schedule never queues a second update while one is
waiting or running, and after a failed one it waits ``RETRY_AFTER`` before trying again.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Self

RETRY_AFTER = timedelta(hours=1)
"""How long the schedule waits after a scheduled update fails, at most its own interval."""

_NAMED = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(weeks=1)}
_OFF = {"off", "never", "manual"}
_DAILY_AT = re.compile(r"daily at (\d{1,2}):(\d{2})")
_EVERY = re.compile(r"every (\d+) (minute|hour|day)s?")


@dataclass(frozen=True, slots=True)
class Schedule:
    """Run every ``every`` (None: never), or once a day after the local time ``at``."""

    every: timedelta | None
    at: time | None = None

    @classmethod
    def parse(cls, text: str) -> Self:
        spec = " ".join(text.lower().split())
        if spec in _OFF:
            return cls(None)
        if spec in _NAMED:
            return cls(_NAMED[spec])
        if match := _DAILY_AT.fullmatch(spec):
            hour, minute = int(match[1]), int(match[2])
            if hour > 23 or minute > 59:
                raise ValueError(f"{text!r}: {hour}:{minute:02d} isn't a time of day")
            return cls(timedelta(days=1), time(hour, minute))
        if match := _EVERY.fullmatch(spec):
            amount, unit = int(match[1]), match[2]
            every = timedelta(**{f"{unit}s": amount})
            if every < timedelta(minutes=5):
                raise ValueError(f"{text!r}: updates can run at most every 5 minutes")
            return cls(every)
        raise ValueError(
            f"{text!r} isn't a schedule; use off, hourly, daily, weekly, 'daily at 06:30' "
            "or 'every 6 hours'"
        )

    @property
    def enabled(self) -> bool:
        return self.every is not None

    def due(
        self, *, now: datetime, last_success: datetime | None, last_attempt: datetime | None
    ) -> bool:
        """Whether an update should start now, given the last successful one and the last try.

        Times must be timezone-aware. ``daily at`` compares in ``now``'s local time zone.
        """
        if self.every is None:
            return False
        if last_attempt is not None and now - last_attempt < min(RETRY_AFTER, self.every):
            return False
        if last_success is None:
            return True
        if self.at is None:
            return now - last_success >= self.every
        local = now.astimezone()
        slot = local.replace(hour=self.at.hour, minute=self.at.minute, second=0, microsecond=0)
        if slot > local:
            slot -= timedelta(days=1)
        return last_success < slot
