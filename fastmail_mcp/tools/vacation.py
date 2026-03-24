"""Vacation / out-of-office auto-reply tools (RFC 8621 VacationResponse)."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, get_account_id, jmap_client
from fastmail_mcp.dependencies import FastmailApiTokenDependency

VACATION_CAPABILITY = "urn:ietf:params:jmap:vacationresponse"
VACATION_USING = ["urn:ietf:params:jmap:core", VACATION_CAPABILITY]


def register(mcp: FastMCP):

    @mcp.tool()
    async def get_vacation_response(
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get the current vacation / out-of-office auto-reply configuration.

        Requires the ``urn:ietf:params:jmap:vacationresponse`` capability
        (Fastmail scope: *Vacation responses*).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, VACATION_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            VACATION_USING,
            [["VacationResponse/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        data = extract_response(responses, "c0")
        items = data.get("list", [])
        if not items:
            return {"message": "No vacation response configured."}

        vr = items[0]
        return {
            "id": vr.get("id"),
            "isEnabled": vr.get("isEnabled"),
            "fromDate": vr.get("fromDate"),
            "toDate": vr.get("toDate"),
            "subject": vr.get("subject"),
            "textBody": vr.get("textBody"),
            "htmlBody": vr.get("htmlBody"),
        }

    @mcp.tool()
    async def set_vacation_response(
        is_enabled: bool,
        from_date: str = "",
        to_date: str = "",
        subject: str = "",
        text_body: str = "",
        html_body: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Set or update the vacation / out-of-office auto-reply.

        Args:
            is_enabled: Whether the vacation response is active.
            from_date: Start date (ISO 8601, e.g. "2024-12-20T00:00:00Z"). Empty to leave unchanged.
            to_date: End date (ISO 8601). Empty to leave unchanged.
            subject: Auto-reply subject line. Empty to leave unchanged.
            text_body: Plain-text auto-reply body.
            html_body: HTML auto-reply body (optional).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, VACATION_CAPABILITY)

        get_responses = await jmap_client.request(
            token,
            session.api_url,
            VACATION_USING,
            [["VacationResponse/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        get_data = extract_response(get_responses, "c0")
        items = get_data.get("list", [])
        if not items:
            raise ToolError("No vacation response object found in this account.")

        vr_id = items[0]["id"]
        patch: dict[str, Any] = {"isEnabled": is_enabled}
        if from_date:
            patch["fromDate"] = from_date
        if to_date:
            patch["toDate"] = to_date
        if subject:
            patch["subject"] = subject
        if text_body:
            patch["textBody"] = text_body
        if html_body:
            patch["htmlBody"] = html_body

        responses = await jmap_client.request(
            token,
            session.api_url,
            VACATION_USING,
            [["VacationResponse/set", {"accountId": account_id, "update": {vr_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        if vr_id not in data.get("updated", {}):
            err = data.get("notUpdated", {}).get(vr_id, {})
            raise ToolError(
                f"Failed to update vacation response: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": vr_id, "isEnabled": is_enabled, "updated": True}
