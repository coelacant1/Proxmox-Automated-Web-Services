"""OAuth2/OIDC service for Authentik integration."""

import httpx

from app.core.config import settings


class OAuthService:
    def __init__(self):
        self._cached_config: dict[str, str] | None = None

    def _get_config_sync(self) -> dict[str, str]:
        """Resolve OAuth config: DB first, env fallback (cached)."""
        if self._cached_config is not None:
            return self._cached_config
        try:
            from app.core.config_resolver import get_config_value_sync

            cfg = {
                "provider_url": get_config_value_sync("oauth_provider_url", settings.oauth_provider_url).rstrip("/"),
                "client_id": get_config_value_sync("oauth_client_id", settings.oauth_client_id),
                "client_secret": get_config_value_sync("oauth_client_secret", settings.oauth_client_secret),
            }
        except Exception:
            cfg = {
                "provider_url": settings.oauth_provider_url.rstrip("/"),
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
            }
        self._cached_config = cfg
        return cfg

    def invalidate_config(self) -> None:
        """Clear cached config (called when admin updates OAuth settings)."""
        self._cached_config = None

    @property
    def provider_url(self) -> str:
        return self._get_config_sync()["provider_url"]

    @property
    def client_id(self) -> str:
        return self._get_config_sync()["client_id"]

    @property
    def client_secret(self) -> str:
        return self._get_config_sync()["client_secret"]

    @property
    def authorize_url(self) -> str:
        return f"{self.provider_url}/authorize/"

    @property
    def token_url(self) -> str:
        return f"{self.provider_url}/token/"

    @property
    def userinfo_url(self) -> str:
        return f"{self.provider_url}/userinfo/"

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.authorize_url}?{query}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_userinfo(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()


oauth_service = OAuthService()
