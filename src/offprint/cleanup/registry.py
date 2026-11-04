"""The named cleanup steps, so QA reports (#6) can say which ones ran.

A step is a pure function: it returns new data and never mutates its input. Thresholds come in as
arguments or an options object, never as constants scattered through the code.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

type Stage = Literal["text", "caption", "table", "paragraph"]


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupStep:
    name: str
    stage: Stage
    function: Callable[..., Any]


_STEPS: dict[str, CleanupStep] = {}


def step[F: Callable[..., Any]](name: str, stage: Stage) -> Callable[[F], F]:
    """Register the decorated function as a cleanup step under a stable, unique name."""

    def register(function: F) -> F:
        if name in _STEPS:
            raise ValueError(f"cleanup step {name!r} is already registered")
        _STEPS[name] = CleanupStep(name=name, stage=stage, function=function)
        return function

    return register


def registered(stage: Stage | None = None) -> tuple[CleanupStep, ...]:
    """Return the steps in registration order, optionally only those of one stage."""
    return tuple(item for item in _STEPS.values() if stage is None or item.stage == stage)
