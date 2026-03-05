"""OAuth2/OIDC service for Authentik integration."""

import httpx

from app.core.config import settings


class OAuthService:
    def __init__(self):
        self.provider_url = settings.oauth_provider_url.rstrip("/")
        self.client_id = settings.oauth_client_id
        self.client_secret = settings.oauth_client_secret

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
