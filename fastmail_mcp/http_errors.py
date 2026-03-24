import httpx
from fastmcp.exceptions import ToolError


def raise_http_error(response: httpx.Response):
    """Raise ``ToolError`` with HTTP status and response body when the request failed."""
    if response.is_success:
        return

    try:
        snippet = response.text[:2000]
    except Exception:
        snippet = ""

    snippet = snippet.strip()
    if not snippet:
        snippet = response.reason_phrase or "error"

    raise ToolError(f"HTTP {response.status_code}: {snippet}")
