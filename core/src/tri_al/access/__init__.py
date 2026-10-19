"""Access (docs/design.md §5.8): one ``require(action)`` check, and browser protections.

There is no login by default: the core's policy allows everything, since Tri-AL runs on
the machine of the person using it. Every route calls ``require(action)``, so an access
plugin (``registry.set_access_policy``) can add login and roles later without touching a
route. The browser protections in ``tri_al.access.browser`` stay on either way.
"""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from fastapi import HTTPException, Request, status

READ = "read"
"""Reading data, stats, jobs and plugins."""

START_UPDATE = "jobs.update"
CANCEL_JOB = "jobs.cancel"
EDIT_PLUGINS = "plugins.edit"
USE_AI = "ai.use"
"""Running a model (annotating text) or asking a model server what it has."""
EDIT_AI = "ai.edit"

ACTIONS = (READ, START_UPDATE, CANCEL_JOB, EDIT_PLUGINS, USE_AI, EDIT_AI)
"""The actions core routes require; plugin routes may require their own."""


@runtime_checkable
class AccessPolicy(Protocol):
    def allows(self, request: Request, action: str) -> bool:
        """Whether whoever sent ``request`` may do ``action``."""
        ...


class AllowAll:
    """The core's policy: everyone who can reach the server may do everything."""

    def allows(self, request: Request, action: str) -> bool:
        return True


def require(action: str) -> Callable[[Request], None]:
    """A FastAPI dependency that refuses the request (403) unless the policy allows ``action``.

    The policy is ``request.app.state.access_policy``.
    """

    def check(request: Request) -> None:
        policy: AccessPolicy = request.app.state.access_policy
        if not policy.allows(request, action):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"not allowed: {action}")

    check.__name__ = f"require_{action.replace('.', '_')}"
    return check


__all__ = [
    "ACTIONS",
    "CANCEL_JOB",
    "EDIT_AI",
    "EDIT_PLUGINS",
    "READ",
    "START_UPDATE",
    "USE_AI",
    "AccessPolicy",
    "AllowAll",
    "require",
]
