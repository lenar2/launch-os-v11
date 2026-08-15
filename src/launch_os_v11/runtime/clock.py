from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from launch_os_v11.domain.time import utc_now


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current runtime time as an aware UTC datetime."""


class SystemClock:
    def now(self) -> datetime:
        return utc_now()


@dataclass
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current = self.current + delta
