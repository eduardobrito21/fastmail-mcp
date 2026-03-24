"""Sieve script tools — server-side mail filtering (RFC 9661 JMAP for Sieve Scripts).

If the JMAP session does not advertise ``urn:ietf:params:jmap:sieve``, these tools
return a clear error explaining that Fastmail's web-UI "Filters & Rules" may not
be exposed via the API.  Use ``get_jmap_session`` to inspect available capabilities.
"""

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import (
    extract_response,
    get_account_id,
    jmap_client,
    resolve_download_url,
)
from fastmail_mcp.client.models import JmapSession
from fastmail_mcp.dependencies import FastmailApiTokenDependency

SIEVE_CAPABILITY = "urn:ietf:params:jmap:sieve"
SIEVE_USING = ["urn:ietf:params:jmap:core", SIEVE_CAPABILITY]


def _check_sieve(session: JmapSession):
    if SIEVE_CAPABILITY not in session.capabilities:
        caps = ", ".join(sorted(session.capabilities.keys()))
        raise ToolError(
            f"Sieve scripts ({SIEVE_CAPABILITY}) are not available in this JMAP session. "
            + "Fastmail's 'Filters & Rules' from the web UI may not be exposed via the API. "
            + "Manage them at https://app.fastmail.com/settings/rules instead.\n\n"
            + f"Available capabilities: {caps}"
        )


def register(mcp: FastMCP):

    @mcp.tool()
    async def list_sieve_scripts(
        token: str = FastmailApiTokenDependency,
    ) -> list[dict[str, Any]]:
        """List Sieve filter scripts (server-side mail routing rules).

        Requires ``urn:ietf:params:jmap:sieve`` in the JMAP session.
        If unavailable, manage filters via the Fastmail web UI (Settings → Filters & Rules).
        """
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [["SieveScript/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "isActive": s.get("isActive"),
                "blobId": s.get("blobId"),
            }
            for s in data.get("list", [])
        ]

    @mcp.tool()
    async def get_sieve_script(
        script_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get a Sieve script by ID, including its full content (downloaded from blob storage)."""
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [
                [
                    "SieveScript/get",
                    {"accountId": account_id, "ids": [script_id]},
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        not_found = data.get("notFound", [])
        scripts = data.get("list", [])
        if script_id in not_found or not scripts:
            raise ToolError(f"Sieve script '{script_id}' not found.")

        script = scripts[0]
        blob_id = script.get("blobId")
        if blob_id:
            dl_url = resolve_download_url(
                session.download_url, account_id, blob_id,
                name="script.sieve", accept="application/sieve",
            )
            script["content"] = await jmap_client.download_blob(token, dl_url)

        return script

    @mcp.tool()
    async def validate_sieve_script(
        content: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Validate Sieve script syntax without saving.

        Args:
            content: The Sieve script source to validate.
        """
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        upload_url = session.upload_url.replace("{accountId}", account_id)
        blob_id = await jmap_client.upload_blob(
            token, upload_url, content.encode("utf-8"), "application/sieve",
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [["SieveScript/validate", {"accountId": account_id, "blobId": blob_id}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return data

    @mcp.tool()
    async def create_sieve_script(
        name: str,
        content: str,
        is_active: bool = False,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Create a new Sieve filter script.

        Args:
            name: Script name.
            content: Sieve script source.
            is_active: Activate this script immediately (only one script can be active).
        """
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        upload_url = session.upload_url.replace("{accountId}", account_id)
        blob_id = await jmap_client.upload_blob(
            token, upload_url, content.encode("utf-8"), "application/sieve",
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [
                [
                    "SieveScript/set",
                    {
                        "accountId": account_id,
                        "create": {
                            "new0": {"name": name, "blobId": blob_id, "isActive": is_active},
                        },
                    },
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "new0" not in created:
            err = data.get("notCreated", {}).get("new0", {})
            raise ToolError(
                f"Failed to create Sieve script: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": created["new0"]["id"], "name": name, "isActive": is_active}

    @mcp.tool()
    async def update_sieve_script(
        script_id: str,
        name: str = "",
        content: str = "",
        is_active: bool | None = None,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Update an existing Sieve script (name, content, or active state).

        Args:
            script_id: ID of the Sieve script to update.
            name: New name (empty to leave unchanged).
            content: New Sieve source (empty to leave unchanged).
            is_active: Set active state (null to leave unchanged).
        """
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        patch: dict[str, Any] = {}
        if name:
            patch["name"] = name
        if content:
            upload_url = session.upload_url.replace("{accountId}", account_id)
            blob_id = await jmap_client.upload_blob(
                token, upload_url, content.encode("utf-8"), "application/sieve",
            )
            patch["blobId"] = blob_id
        if is_active is not None:
            patch["isActive"] = is_active

        if not patch:
            raise ToolError("Nothing to update — supply name, content, or is_active.")

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [
                [
                    "SieveScript/set",
                    {"accountId": account_id, "update": {script_id: patch}},
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        if script_id not in data.get("updated", {}):
            err = data.get("notUpdated", {}).get(script_id, {})
            raise ToolError(
                f"Failed to update Sieve script: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": script_id, "updated": True}

    @mcp.tool()
    async def destroy_sieve_script(
        script_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Destroy (delete) a Sieve script. Cannot destroy the currently active script."""
        session = await jmap_client.get_session(token)
        _check_sieve(session)
        account_id = get_account_id(session, SIEVE_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            SIEVE_USING,
            [
                [
                    "SieveScript/set",
                    {"accountId": account_id, "destroy": [script_id]},
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        if script_id not in data.get("destroyed", []):
            err = data.get("notDestroyed", {}).get(script_id, {})
            raise ToolError(
                f"Failed to destroy Sieve script: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": script_id, "destroyed": True}
