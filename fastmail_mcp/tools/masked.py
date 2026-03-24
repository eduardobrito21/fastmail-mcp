"""Masked Email tools — Fastmail extension (https://www.fastmail.com/dev/maskedemail)."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, get_account_id, jmap_client
from fastmail_mcp.dependencies import FastmailApiTokenDependency

MASKED_CAPABILITY = "https://www.fastmail.com/dev/maskedemail"
MASKED_USING = ["urn:ietf:params:jmap:core", MASKED_CAPABILITY]


def register(mcp: FastMCP):

    @mcp.tool()
    async def list_masked_emails(
        state_filter: str = "",
        limit: int = 50,
        offset: int = 0,
        verbose: bool = False,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """List masked (alias) email addresses with pagination.

        Returns a compact summary by default. Set ``verbose=True`` for full fields.

        Args:
            state_filter: Filter by state (pending/enabled/disabled/deleted). Empty for all.
            limit: Max items to return (default 50, max 200).
            offset: Skip this many items (for pagination).
            verbose: If True, return all fields; if False, return compact summary.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MASKED_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MASKED_USING,
            [["MaskedEmail/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        data = extract_response(responses, "c0")
        emails = data.get("list", [])

        if state_filter:
            emails = [e for e in emails if e.get("state") == state_filter]

        total = len(emails)
        limit = min(max(limit, 1), 200)
        page = emails[offset : offset + limit]

        if verbose:
            items = [
                {
                    "id": e.get("id"),
                    "email": e.get("email"),
                    "state": e.get("state"),
                    "forDomain": e.get("forDomain"),
                    "description": e.get("description"),
                    "url": e.get("url"),
                    "lastMessageAt": e.get("lastMessageAt"),
                    "createdAt": e.get("createdAt"),
                    "createdBy": e.get("createdBy"),
                }
                for e in page
            ]
        else:
            items = [
                {
                    "id": e.get("id"),
                    "email": e.get("email"),
                    "state": e.get("state"),
                    "forDomain": e.get("forDomain", ""),
                    "description": e.get("description", ""),
                }
                for e in page
            ]

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "count": len(items),
            "hasMore": offset + limit < total,
            "items": items,
        }

    @mcp.tool()
    async def create_masked_email(
        for_domain: str,
        description: str = "",
        url: str = "",
        state: str = "enabled",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Create a new masked (alias) email address.

        Addresses created in "pending" state expire after 24 hours if not enabled.

        Args:
            for_domain: Domain this masked email is associated with (e.g. "example.com").
            description: Human-readable description.
            url: URL associated with this masked email.
            state: Initial state — "enabled" (default) or "pending".
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MASKED_CAPABILITY)

        create_obj: dict[str, Any] = {
            "forDomain": for_domain,
            "state": state,
        }
        if description:
            create_obj["description"] = description
        if url:
            create_obj["url"] = url

        responses = await jmap_client.request(
            token,
            session.api_url,
            MASKED_USING,
            [["MaskedEmail/set", {"accountId": account_id, "create": {"new0": create_obj}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "new0" not in created:
            err = data.get("notCreated", {}).get("new0", {})
            raise ToolError(
                f"Failed to create masked email: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return created["new0"]

    @mcp.tool()
    async def update_masked_email(
        masked_email_id: str,
        state: str = "",
        description: str = "",
        for_domain: str = "",
        url: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Update a masked email address (change state, description, domain, or URL).

        Args:
            masked_email_id: ID of the masked email to update.
            state: New state (enabled/disabled/deleted). Empty to leave unchanged.
            description: New description. Empty to leave unchanged.
            for_domain: New associated domain. Empty to leave unchanged.
            url: New associated URL. Empty to leave unchanged.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MASKED_CAPABILITY)

        patch: dict[str, Any] = {}
        if state:
            patch["state"] = state
        if description:
            patch["description"] = description
        if for_domain:
            patch["forDomain"] = for_domain
        if url:
            patch["url"] = url

        if not patch:
            raise ToolError("Nothing to update — supply at least one field to change.")

        responses = await jmap_client.request(
            token,
            session.api_url,
            MASKED_USING,
            [
                [
                    "MaskedEmail/set",
                    {"accountId": account_id, "update": {masked_email_id: patch}},
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        if masked_email_id not in data.get("updated", {}):
            err = data.get("notUpdated", {}).get(masked_email_id, {})
            raise ToolError(
                f"Failed to update masked email: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": masked_email_id, "updated": True}

    @mcp.tool()
    async def destroy_masked_email(
        masked_email_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Destroy (permanently delete) a masked email address."""
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MASKED_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MASKED_USING,
            [
                [
                    "MaskedEmail/set",
                    {"accountId": account_id, "destroy": [masked_email_id]},
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        if masked_email_id not in data.get("destroyed", []):
            err = data.get("notDestroyed", {}).get(masked_email_id, {})
            raise ToolError(
                f"Failed to destroy masked email: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": masked_email_id, "destroyed": True}
