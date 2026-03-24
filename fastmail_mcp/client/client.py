"""Thin JMAP HTTP client — session discovery + method-call batches."""

from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from fastmail_mcp.config import settings
from fastmail_mcp.http_errors import raise_http_error

from .models import JmapSession


class JmapClient:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def get_session(self, token: str):
        resp = await self.http.get(
            settings.fastmail_jmap_session_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        raise_http_error(resp)
        return JmapSession.model_validate(resp.json())

    async def request(
        self,
        token: str,
        api_url: str,
        using: list[str],
        method_calls: list[list[Any]],
    ) -> list[list[Any]]:
        body: dict[str, Any] = {"using": using, "methodCalls": method_calls}
        resp = await self.http.post(
            api_url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        raise_http_error(resp)
        data = resp.json()
        return data.get("methodResponses", [])

    async def upload_blob(
        self,
        token: str,
        upload_url: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """Upload raw bytes to the JMAP upload endpoint and return the ``blobId``."""
        resp = await self.http.post(
            upload_url,
            content=content,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
        )
        raise_http_error(resp)
        return resp.json()["blobId"]

    async def download_blob(
        self,
        token: str,
        download_url: str,
    ) -> str:
        """Download a blob by its fully-resolved URL and return the text content."""
        resp = await self.http.get(
            download_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        raise_http_error(resp)
        return resp.text

    async def aclose(self):
        await self.http.aclose()


def get_account_id(session: JmapSession, capability: str):
    """Look up the primary account ID for *capability*, raising ``ToolError`` if absent."""
    account_id = session.primary_accounts.get(capability)
    if not account_id:
        raise ToolError(
            f"Capability '{capability}' not available in this JMAP session. "
            + "Check your API token scopes at https://www.fastmail.com/dev/"
        )
    return account_id


def extract_response(responses: list[list[Any]], call_id: str) -> dict[str, Any]:
    """Find the method response matching *call_id*, raising ``ToolError`` on JMAP errors."""
    for resp in responses:
        name: str = resp[0]
        data: dict[str, Any] = resp[1]
        cid: str = resp[2]
        if cid == call_id:
            if name == "error":
                raise ToolError(
                    f"JMAP error ({data.get('type', 'unknown')}): {data.get('description', '')}"
                )
            return data
    raise ToolError(f"No JMAP response for call '{call_id}'")


def resolve_download_url(
    template: str,
    account_id: str,
    blob_id: str,
    name: str = "download",
    accept: str = "application/octet-stream",
):
    """Expand the RFC 6570 download-URL template from the JMAP session."""
    return (
        template.replace("{accountId}", account_id)
        .replace("{blobId}", blob_id)
        .replace("{name}", name)
        .replace("{type}", accept)
    )


jmap_client = JmapClient()
