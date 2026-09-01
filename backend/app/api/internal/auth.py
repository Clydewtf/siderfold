from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest

from fastapi import Header, HTTPException, Request, status


@dataclass(frozen=True)
class InternalAccess:
    actor: str


def require_internal_access(
    request: Request,
    authorization: str | None = Header(default=None),
) -> InternalAccess:
    """Require the one configured operator token without exposing its value."""

    configured_token = request.app.state.settings.internal_api_token
    if configured_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    scheme, _, supplied_token = (authorization or "").partition(" ")
    expected_token = configured_token.get_secret_value()
    if scheme.lower() != "bearer" or not supplied_token or not compare_digest(
        supplied_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return InternalAccess(actor=request.app.state.settings.internal_operator_id)
