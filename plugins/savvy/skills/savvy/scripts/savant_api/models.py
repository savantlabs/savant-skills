from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_ORIGIN = "https://app.savantlabs.io"


class SavantAppApiError(RuntimeError):
    """Raised when the internal app API helper cannot complete a request."""


@dataclass(frozen=True)
class FlowUrl:
    origin: str
    flow_id: str
    namespace: str | None
    url: str


@dataclass(frozen=True)
class SavantUrl:
    origin: str
    url: str
    kind: str
    flow_id: str | None = None
    folder_id: str | None = None
    namespace: str | None = None


@dataclass(frozen=True)
class SavantSessionContext:
    origin: str
    namespace: str | None
    tab_id: str
    access_token: str
    browser_profile: str
    workspace_id: str | None = None
    org_id: str | None = None
    user: dict[str, Any] | None = None
    organization: dict[str, Any] | None = None
    workspace: dict[str, Any] | None = None
