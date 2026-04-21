"""Rate-limiting, analytics, and setup-guard middleware using Redis."""

import time

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.security import decode_token
from app.services.rate_limiter import check_api_rate_limit


class SetupGuardMiddleware(BaseHTTPMiddleware):
    """Returns 503 with setup_required flag when the app has not been initialized."""

    ALLOWED_PREFIXES = (
        "/api/setup",
        "/health",
        "/docs",
        "/openapi.json",
        "/favicon",
    )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        from app.core.setup_state import is_initialized

        if is_initialized():
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self.ALLOWED_PREFIXES):
            return await call_next(request)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Application has not been initialized",
                "setup_required": True,
            },
        )


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """Tracks per-user request counts and active sessions in Redis."""

    EXEMPT_PREFIXES = ("/health", "/docs", "/openapi.json", "/favicon")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        user_id = self._extract_user_id(request)
        response = await call_next(request)

        # Fire-and-forget analytics recording
        try:
            from app.services.rate_limiter import get_redis

            r = await get_redis()
            now = time.time()
            hour_bucket = int(now // 3600) * 3600
            pipe = r.pipeline()

            # Total request counter per hour bucket
            req_key = f"analytics:requests:{hour_bucket}"
            pipe.incr(req_key)
            pipe.expire(req_key, 86400 * 7)  # keep 7 days

            if user_id:
                # Per-user request counter per hour
                user_req_key = f"analytics:user_requests:{user_id}:{hour_bucket}"
                pipe.incr(user_req_key)
                pipe.expire(user_req_key, 86400 * 7)

                # Active user heartbeat (sorted set: user_id -> last_seen timestamp)
                pipe.zadd("analytics:active_users", {user_id: now})

                # Endpoint usage counter per hour
                endpoint_key = f"analytics:endpoints:{hour_bucket}"
                pipe.hincrby(endpoint_key, f"{request.method} {path}", 1)
                pipe.expire(endpoint_key, 86400 * 7)

            await pipe.execute()
        except Exception:
            pass  # fail open

        return response

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_token(auth_header[7:])
            if payload and payload.get("sub"):
                return payload["sub"]
        token = request.cookies.get("paws_access_token")
        if token:
            payload = decode_token(token)
            if payload and payload.get("sub"):
                return payload["sub"]
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies per-user API rate limiting. Unauthenticated requests use client IP."""

    EXEMPT_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
    }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Only rate-limit mutating requests; reads are freely allowed
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Identify the caller
        identity = self._get_identity(request)

        try:
            allowed, remaining = await check_api_rate_limit(identity)
        except Exception:
            # If Redis is down, allow the request (fail open)
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    @staticmethod
    def _get_identity(request: Request) -> str:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_token(token)
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        return f"ip:{request.client.host}" if request.client else "ip:unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
        )
        # Allow Swagger UI CDN on docs pages
        if request.url.path in ("/docs", "/redoc", "/openapi.json"):
            csp = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
                "font-src 'self' https://cdn.jsdelivr.net; frame-ancestors 'none'"
            )
        response.headers["Content-Security-Policy"] = csp
        # Only add HSTS if request came via HTTPS (behind reverse proxy)
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
