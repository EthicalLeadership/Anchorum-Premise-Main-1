"""Unconditional authentication baseline (CR-10.6).

The threat model mandates that loopback is not a security boundary. Every
request must be authenticated, and state-changing requests must pass Origin
checks. This applies in every deployment mode.

Whether to enforce auth is a create_app parameter (require_auth, default True)
stored on app.state. It is NOT read from an environment variable. The earlier
PYTEST_CURRENT_TEST bypass meant that anything that could set the server's
environment (a wrapper script, a .env file, a systemd or launchd unit, a CI
runner) could disable Host and Origin enforcement with no code change and no
diff to review. Tests disable it via the conftest wrapper, which only loads
when pytest runs — a production deploy that does not run pytest cannot reach
it.

Deployment-time configuration:
    ANCHORUM_ALLOWED_HOSTS    comma-separated host[:port] additions
                              (default set: localhost/127.0.0.1 on 8000 & 5173, testserver)
    ANCHORUM_ALLOWED_ORIGINS  comma-separated scheme://host[:port] additions
                              (default set: localhost/127.0.0.1 on 5173 & 8000)

Both env vars are additive: unlisted hosts and origins are still rejected.
/health is exempt from all checks so probes and load balancers can reach it
from any host or origin, with no credential.
"""
import os
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _merge_env(env_var: str, defaults: frozenset) -> frozenset:
    """Return defaults plus any comma-separated values from env_var."""
    raw = os.environ.get(env_var, "")
    extras = frozenset(part.strip() for part in raw.split(",") if part.strip())
    return defaults | extras


_DEFAULT_HOSTS = frozenset({
    "localhost:8000",
    "127.0.0.1:8000",
    "localhost:5173",
    "127.0.0.1:5173",
    "testserver",
})
ALLOWED_HOSTS = _merge_env("ANCHORUM_ALLOWED_HOSTS", _DEFAULT_HOSTS)

_DEFAULT_ORIGINS = frozenset({
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
})
ALLOWED_ORIGINS = _merge_env("ANCHORUM_ALLOWED_ORIGINS", _DEFAULT_ORIGINS)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Enforcement is a create_app parameter, not an environment variable.
        # Defaults to True if for any reason the state attribute is absent.
        require_auth = getattr(request.app.state, "require_auth", True)
        if not require_auth:
            return await call_next(request)

        # /health is exempt from every check (probes, load balancers).
        if request.url.path == "/health":
            return await call_next(request)

        # 1. Host check
        host = request.headers.get("host", "").lower()
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"error": "INVALID_HOST"}, status_code=400)

        # 2. Origin / CSRF check on state-changing methods
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            origin = request.headers.get("origin")
            if origin and origin.lower() not in ALLOWED_ORIGINS:
                return JSONResponse({"error": "INVALID_ORIGIN"}, status_code=403)

            if not origin:
                api_key = request.headers.get("x-anchorum-key")
                expected = getattr(request.app.state, "api_key", None)
                if expected and api_key != expected:
                    return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

        # 3. API-key requirement on all API routes
        if request.url.path.startswith(("/board/", "/ledger/", "/cases/")):
            api_key = request.headers.get("x-anchorum-key")
            expected = getattr(request.app.state, "api_key", None)
            if expected and api_key != expected:
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

        return await call_next(request)
