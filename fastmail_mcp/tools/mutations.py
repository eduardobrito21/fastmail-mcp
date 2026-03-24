"""Email mutation tools — single + bulk operations (read, pin, delete, move, labels)."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, get_account_id, jmap_client
from fastmail_mcp.dependencies import FastmailApiTokenDependency

from ._helpers import MAIL_CAPABILITY, MAIL_USING, parse_id_list, resolve_mailbox_by_role

MAX_BULK = 50


def _check_update_errors(data: dict[str, Any]):
    """Raise ``ToolError`` if any IDs were not updated."""
    not_updated: dict[str, Any] = data.get("notUpdated", {})
    if not_updated:
        errors = "; ".join(
            f"{eid}: {err.get('type', 'unknown')} — {err.get('description', '')}"
            for eid, err in not_updated.items()
        )
        raise ToolError(f"Some emails could not be updated: {errors}")


def register(mcp: FastMCP):

    # -- Single mutations --------------------------------------------------------

    @mcp.tool()
    async def mark_email_read(
        email_id: str,
        read: bool = True,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Mark an email as read or unread.

        Args:
            email_id: ID of the email.
            read: True to mark as read (default), false to mark as unread.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        patch: dict[str, Any] = {"keywords/$seen": True} if read else {"keywords/$seen": None}
        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": {email_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "read": read}

    @mcp.tool()
    async def pin_email(
        email_id: str,
        pinned: bool = True,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Pin (flag) or unpin an email.

        Args:
            email_id: ID of the email.
            pinned: True to pin/flag (default), false to unpin.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        patch: dict[str, Any] = (
            {"keywords/$flagged": True} if pinned else {"keywords/$flagged": None}
        )
        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": {email_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "pinned": pinned}

    @mcp.tool()
    async def delete_email(
        email_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Move an email to the Trash mailbox."""
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        trash_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "trash")
        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/set",
                    {
                        "accountId": account_id,
                        "update": {email_id: {"mailboxIds": {trash_id: True}}},
                    },
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "deleted": True, "trashMailboxId": trash_id}

    @mcp.tool()
    async def move_email(
        email_id: str,
        mailbox_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Move an email to a different mailbox (replaces all current mailbox assignments).

        Args:
            email_id: ID of the email to move.
            mailbox_id: Target mailbox ID.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/set",
                    {
                        "accountId": account_id,
                        "update": {email_id: {"mailboxIds": {mailbox_id: True}}},
                    },
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "movedTo": mailbox_id}

    @mcp.tool()
    async def add_labels(
        email_id: str,
        mailbox_ids: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Add one or more mailbox labels to an email (without removing existing ones).

        Args:
            email_id: ID of the email.
            mailbox_ids: Comma-separated mailbox IDs to add.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        mids = parse_id_list(mailbox_ids)
        patch = {f"mailboxIds/{mid}": True for mid in mids}
        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": {email_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "labelsAdded": mids}

    @mcp.tool()
    async def remove_labels(
        email_id: str,
        mailbox_ids: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Remove one or more mailbox labels from an email.

        Args:
            email_id: ID of the email.
            mailbox_ids: Comma-separated mailbox IDs to remove.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        mids = parse_id_list(mailbox_ids)
        patch: dict[str, Any] = {f"mailboxIds/{mid}": None for mid in mids}
        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": {email_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        _check_update_errors(data)
        return {"id": email_id, "labelsRemoved": mids}

    # -- Bulk mutations ----------------------------------------------------------

    @mcp.tool()
    async def bulk_mark_read(
        email_ids: str,
        read: bool = True,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Mark multiple emails as read or unread.

        Args:
            email_ids: Comma-separated email IDs (max 50).
            read: True to mark as read, false for unread.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        ids = parse_id_list(email_ids)[:MAX_BULK]
        patch: dict[str, Any] = {"keywords/$seen": True} if read else {"keywords/$seen": None}
        updates = dict.fromkeys(ids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "read": read,
        }

    @mcp.tool()
    async def bulk_pin(
        email_ids: str,
        pinned: bool = True,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Pin (flag) or unpin multiple emails.

        Args:
            email_ids: Comma-separated email IDs (max 50).
            pinned: True to pin, false to unpin.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        ids = parse_id_list(email_ids)[:MAX_BULK]
        patch: dict[str, Any] = (
            {"keywords/$flagged": True} if pinned else {"keywords/$flagged": None}
        )
        updates = dict.fromkeys(ids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "pinned": pinned,
        }

    @mcp.tool()
    async def bulk_move(
        email_ids: str,
        mailbox_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Move multiple emails to a mailbox (replaces existing mailbox assignments).

        Args:
            email_ids: Comma-separated email IDs (max 50).
            mailbox_id: Target mailbox ID.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        ids = parse_id_list(email_ids)[:MAX_BULK]
        patch = {"mailboxIds": {mailbox_id: True}}
        updates = dict.fromkeys(ids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "movedTo": mailbox_id,
        }

    @mcp.tool()
    async def bulk_delete(
        email_ids: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Move multiple emails to Trash.

        Args:
            email_ids: Comma-separated email IDs (max 50).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        trash_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "trash")
        ids = parse_id_list(email_ids)[:MAX_BULK]
        patch = {"mailboxIds": {trash_id: True}}
        updates = dict.fromkeys(ids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "deleted": True,
        }

    @mcp.tool()
    async def bulk_add_labels(
        email_ids: str,
        mailbox_ids: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Add mailbox labels to multiple emails.

        Args:
            email_ids: Comma-separated email IDs (max 50).
            mailbox_ids: Comma-separated mailbox IDs to add.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        eids = parse_id_list(email_ids)[:MAX_BULK]
        mids = parse_id_list(mailbox_ids)
        patch = {f"mailboxIds/{mid}": True for mid in mids}
        updates = dict.fromkeys(eids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "labelsAdded": mids,
        }

    @mcp.tool()
    async def bulk_remove_labels(
        email_ids: str,
        mailbox_ids: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Remove mailbox labels from multiple emails.

        Args:
            email_ids: Comma-separated email IDs (max 50).
            mailbox_ids: Comma-separated mailbox IDs to remove.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        eids = parse_id_list(email_ids)[:MAX_BULK]
        mids = parse_id_list(mailbox_ids)
        patch: dict[str, Any] = {f"mailboxIds/{mid}": None for mid in mids}
        updates = dict.fromkeys(eids, patch)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "update": updates}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return {
            "updated": list(data.get("updated", {}).keys()),
            "notUpdated": data.get("notUpdated", {}),
            "labelsRemoved": mids,
        }
