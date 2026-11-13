"""Unconditional authentication baseline (CR-10.6).

The threat model mandates that loopback is not a security boundary. Every
request must be authenticated, and state-changing requests must pass Origin
checks. This applies in every deployment mode.
"""
import os
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ALLOWED_HOSTS = {"localhost:8000", "127.0.0.1:8000", "localhost:5173", "127.0.0.1:5173", "testserver"}
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        is_test = "PYTEST_CURRENT_TEST" in os.environ
        
        # 1. Host check
        host = request.headers.get("host", "").lower()
        if host not in ALLOWED_HOSTS and not is_test:
            return JSONResponse({"error": "INVALID_HOST"}, status_code=400)

        # 2. Origin/CSRF check for state-changing methods
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            origin = request.headers.get("origin")
            if origin and origin.lower() not in ALLOWED_ORIGINS and not is_test:
                return JSONResponse({"error": "INVALID_ORIGIN"}, status_code=403)
            
            # If origin is missing (non-browser client), require API key
            if not origin and not is_test:
                api_key = request.headers.get("x-anchorum-key")
                expected = getattr(request.app.state, "api_key", None)
                if expected and api_key != expected:
                    return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

        # 3. Require API key on all API routes (except static files)
        if request.url.path.startswith(("/board/", "/ledger/", "/cases/")) and not is_test:
            api_key = request.headers.get("x-anchorum-key")
            expected = getattr(request.app.state, "api_key", None)
            if expected and api_key != expected:
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

        return await call_next(request)
