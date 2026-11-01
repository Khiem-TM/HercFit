"""Who is reading: the user, or the assistant acting for the user.

The authentication dependency sets the principal for the request. Domain reads
of health data ask `current()` instead of inspecting headers, so the decision
"may the assistant see this?" has one input everywhere.

* USER: a normal access token.
* AGENT: a delegated token the backend issued to the agent service after it
  proved itself (POST /api/v2/auth/delegations). During the transition a user
  token carrying the self-declared header `X-HercFit-Client: agent` is also
  treated as AGENT (never with more rights than the user); with
  settings.AGENT_DELEGATION_REQUIRED such tokens are refused.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

AGENT_CLIENT_HEADER = "x-hercfit-client"


class PrincipalKind(StrEnum):
    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    user_id: UUID
    delegated: bool = False           # True only for backend-issued delegated tokens
    consent_version: int | None = None  # consent version seen when the delegation was issued

    @property
    def is_agent(self) -> bool:
        return self.kind is PrincipalKind.AGENT


_current: ContextVar[Principal | None] = ContextVar("hercfit_principal", default=None)


def set_current(principal: Principal | None):
    return _current.set(principal)


def reset(token) -> None:
    _current.reset(token)


def current() -> Principal | None:
    return _current.get()


def is_agent() -> bool:
    principal = _current.get()
    return principal is not None and principal.is_agent
