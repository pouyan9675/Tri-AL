"""Pipeline events that plugins subscribe to with ``registry.on`` (docs/design.md §5.6).

Handlers run in the process that fires the event, after the data they describe is
committed. Each gets the event object. A handler that raises doesn't stop the pipeline or
the other handlers; the error is logged and listed in the run summary's ``handler_errors``.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from tri_al.pipeline.summary import RunSummary

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpdateStarted:
    name: ClassVar[str] = "update.started"
    run_id: int


@dataclass(frozen=True, slots=True)
class TrialsChanged:
    """Trials an update added (``kind="new"``) or changed (``kind="updated"``).

    An install doesn't send it, since every trial is new; handle ``install.finished``.
    """

    name: ClassVar[str] = "trials.changed"
    run_id: int
    ids: tuple[int, ...]
    kind: Literal["new", "updated"]


@dataclass(frozen=True, slots=True)
class UpdateFinished:
    name: ClassVar[str] = "update.finished"
    summary: RunSummary


@dataclass(frozen=True, slots=True)
class InstallFinished:
    """An install finished and its database replaced the old one."""

    name: ClassVar[str] = "install.finished"
    summary: RunSummary


type Event = UpdateStarted | TrialsChanged | UpdateFinished | InstallFinished
type Handler = Callable[[Any], object]

EVENTS: dict[str, type[Event]] = {
    event.name: event for event in (UpdateStarted, TrialsChanged, UpdateFinished, InstallFinished)
}


@dataclass(frozen=True, slots=True)
class Subscription:
    plugin: str
    handler: Handler


def fire(subscriptions: Mapping[str, Sequence[Subscription]], event: Event) -> list[str]:
    """Call every handler subscribed to ``event``; return the errors of those that raised."""
    errors = []
    for subscription in subscriptions.get(event.name, ()):
        try:
            subscription.handler(event)
        except Exception as exc:
            log.exception("plugin %r: %s handler failed", subscription.plugin, event.name)
            errors.append(f"{subscription.plugin}: {event.name} handler failed: {exc!r}")
    return errors
