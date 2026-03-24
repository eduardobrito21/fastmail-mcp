"""Fastmail API token resolution for MCP tools — use ``FastmailApiTokenDependency`` on each tool."""

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers, get_http_request

from fastmail_mcp.config import settings


def get_fastmail_api_token():
    """Resolve the Fastmail API token (Bearer).

    **HTTP**

    1. ``X-Fastmail-Api-Token`` header (best for clients that support it).
    2. ``fastmail_api_token`` query parameter.
    3. Server ``FASTMAIL_API_TOKEN`` env
        — only if ``FASTMAIL_MCP_HTTP_ALLOW_ENV_API_KEY`` is true (default is False)

    **Stdio** (local Cursor, etc.):

    - ``FASTMAIL_API_TOKEN`` in the process environment only; headers/query are unused.
    """

    headers = get_http_headers()
    token = headers.get("x-fastmail-api-token", "").strip()
    if token:
        return token

    try:
        request = get_http_request()
    except RuntimeError:
        request = None

    if request is not None:
        token = request.query_params.get("fastmail_api_token", "").strip()
        if token:
            return token

        if settings.fastmail_mcp_http_allow_env_api_key and settings.fastmail_api_token is not None:
            return settings.fastmail_api_token.get_secret_value()

        raise ToolError(
            "No Fastmail API token for this request. Send header X-Fastmail-Api-Token or set query parameter fastmail_api_token on the MCP URL."
        )

    if settings.fastmail_api_token is not None:
        return settings.fastmail_api_token.get_secret_value()

    raise ToolError(
        "No Fastmail API token found. Set FASTMAIL_API_TOKEN for local stdio, or use HTTP with X-Fastmail-Api-Token or query parameter fastmail_api_token."
    )


FastmailApiTokenDependency = Depends(get_fastmail_api_token)
