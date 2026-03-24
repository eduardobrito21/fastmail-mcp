"""Pydantic models for JMAP session and response objects (RFC 8620)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JmapAccount(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    is_personal: bool = Field(alias="isPersonal")
    is_read_only: bool = Field(alias="isReadOnly")
    account_capabilities: dict[str, Any] = Field(alias="accountCapabilities")


class JmapSession(BaseModel):
    """RFC 8620 Session object — returned by ``GET /jmap/session``."""

    model_config = ConfigDict(populate_by_name=True)

    capabilities: dict[str, Any]
    accounts: dict[str, JmapAccount]
    primary_accounts: dict[str, str] = Field(alias="primaryAccounts")
    username: str
    api_url: str = Field(alias="apiUrl")
    download_url: str = Field(alias="downloadUrl")
    upload_url: str = Field(alias="uploadUrl")
    event_source_url: str = Field(alias="eventSourceUrl")
    state: str
