"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — DPDP Security & Access Control
===============================================================================
Author: Senior Security & Compliance Engineer
Compliance Target:
  - Digital Personal Data Protection Act, 2023 (DPDP Act) — Section 8
  - DPDP Rules, 2025
Components:
  1. Role-Based Access Control (RBAC: anonymous vs service_account vs admin)
  2. TLS & Security Transport Headers Middleware (HSTS, nosniff, DENY)
  3. Role Enforcement Dependencies for Restricted Endpoints
===============================================================================
"""

from enum import Enum
import logging
import secrets
from typing import Callable, List, Optional, Tuple

from fastapi import Header, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import ADMIN_API_KEY, ENFORCE_HSTS, SERVICE_ACCOUNT_API_KEY

logger = logging.getLogger("ksrtc_security")


class Role(str, Enum):
    ANONYMOUS = "anonymous"
    SERVICE_ACCOUNT = "service_account"
    ADMIN = "admin"


# =============================================================================
# 1. TLS & Security Headers Middleware (Section 8 Safeguards)
# =============================================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Enforces defense-in-depth transport security and HTTP response headers:
    - Strict-Transport-Security (HSTS): Enforces browser-level TLS communication.
    - X-Content-Type-Options: Prevents MIME-sniffing attacks.
    - X-Frame-Options: Prevents clickjacking.
    - Referrer-Policy: Protects referrer leakage of personal request paths.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # Inject HSTS for TLS security
        if ENFORCE_HSTS:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


# =============================================================================
# 2. Role Determination & Verification (RBAC)
# =============================================================================
def get_current_role(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    x_service_key: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None),
) -> Tuple[Role, str]:
    """
    Extracts caller credentials and determines actor role:
    - Admin: Full governance, audit trail inspection, and retention purge.
    - Service Account: Internal notification dispatch workers authorized to decrypt PII.
    - Anonymous: Default public riders.
    Uses constant-time comparison to prevent timing attacks.
    """
    # 1. Check explicit Admin header
    if x_admin_key and secrets.compare_digest(x_admin_key, ADMIN_API_KEY):
        return Role.ADMIN, "admin-officer"

    # 2. Check explicit Service Account header
    if x_service_key and secrets.compare_digest(x_service_key, SERVICE_ACCOUNT_API_KEY):
        return Role.SERVICE_ACCOUNT, "dispatch-service-worker"

    # 3. Check generic API key or Authorization Bearer header
    token: Optional[str] = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if token:
        if secrets.compare_digest(token, ADMIN_API_KEY):
            return Role.ADMIN, "admin-bearer"
        if secrets.compare_digest(token, SERVICE_ACCOUNT_API_KEY):
            return Role.SERVICE_ACCOUNT, "dispatch-bearer"
        # Invalid credential provided
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials or API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Default public rider
    return Role.ANONYMOUS, "anonymous-rider"


# =============================================================================
# 3. Role Enforcement Guards
# =============================================================================
def require_role(allowed_roles: List[Role]) -> Callable[..., Tuple[Role, str]]:
    """Factory dependency restricting an endpoint to specific authorized roles."""

    def role_checker(
        authorization: Optional[str] = Header(None),
        x_api_key: Optional[str] = Header(None),
        x_service_key: Optional[str] = Header(None),
        x_admin_key: Optional[str] = Header(None),
    ) -> Tuple[Role, str]:
        role, actor_id = get_current_role(
            authorization=authorization,
            x_api_key=x_api_key,
            x_service_key=x_service_key,
            x_admin_key=x_admin_key,
        )

        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access Denied: Role '{role.value}' is not authorized to execute this operation. "
                    f"Required roles: {[r.value for r in allowed_roles]}."
                ),
            )
        return role, actor_id

    return role_checker


require_admin = require_role([Role.ADMIN])
require_service_or_admin = require_role([Role.SERVICE_ACCOUNT, Role.ADMIN])


def get_current_user() -> Tuple[Role, str]:
    """
    Completely permissive no-auth fallback dependency.
    Always yields an anonymous commuter role without credentials, tokens, or gatekeeping.
    """
    return Role.ANONYMOUS, "anonymous-rider"

