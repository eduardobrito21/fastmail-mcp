from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    fastmail_api_token: SecretStr | None = None
    fastmail_jmap_session_url: str = "https://api.fastmail.com/jmap/session"

    #: If False, HTTP MCP traffic never uses ``FASTMAIL_API_TOKEN`` from the server env — callers must send
    #: ``X-Fastmail-Api-Token`` or ``?fastmail_api_token=`` so each user uses their own token (public multi-tenant).
    fastmail_mcp_http_allow_env_api_key: bool = Field(default=False)


settings = Settings(**{})  # pyright: ignore[reportUnknownArgumentType]
