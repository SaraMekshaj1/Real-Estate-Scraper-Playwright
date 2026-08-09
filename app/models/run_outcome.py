from __future__ import annotations
from enum import Enum, auto


class RunOutcome(Enum):
    COMPLETED = auto()    # crawl finished normally
    INTERRUPTED = auto()  # process died / unhandled exception ended the run early