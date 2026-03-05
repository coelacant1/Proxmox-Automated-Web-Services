"""Rate-limiting middleware using Redis sliding window."""

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.security import decode_token
from app.services.rate_limiter import check_api_rate_limit


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
