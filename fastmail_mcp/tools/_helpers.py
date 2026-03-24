"""Shared helpers for mail tool modules."""

import re

from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, jmap_client

MAIL_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"


def parse_addresses(raw: str) -> list[dict[str, str | None]]:
    """Parse comma-separated addresses into JMAP EmailAddress objects.

    Accepts ``Name <email>``, ``<email>``, or bare ``email`` formats.
    """
    addrs: list[dict[str, str | None]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)\s*<(.+?)>\s*$", part)
        if m:
            addrs.append({"name": m.group(1).strip(), "email": m.group(2).strip()})
        else:
            m2 = re.match(r"^<(.+?)>\s*$", part)
            addrs.append({"name": None, "email": m2.group(1) if m2 else part})
    return addrs


def parse_id_list(csv: str) -> list[str]:
    """Split a comma-separated string into a list of stripped, non-empty IDs."""
    ids = [x.strip() for x in csv.split(",") if x.strip()]
    if not ids:
        raise ToolError("No IDs provided.")
    return ids


async def resolve_mailbox_by_role(
    token: str,
    api_url: str,
    account_id: str,
    role: str,
) -> str:
    """Return the mailbox ID for a given role (``drafts``, ``sent``, ``trash``, ``inbox``, etc.)."""
    responses = await jmap_client.request(
        token,
        api_url,
        MAIL_USING,
        [["Mailbox/get", {"accountId": account_id, "ids": None}, "mb0"]],
    )
    data = extract_response(responses, "mb0")
    for mb in data.get("list", []):
        if mb.get("role") == role:
            return mb["id"]
    raise ToolError(f"No mailbox with role '{role}' found in this account.")


async def resolve_mailbox_by_name_or_role(
    token: str,
    api_url: str,
    account_id: str,
    name_or_role: str,
) -> str:
    """Return the mailbox ID matching *name_or_role* (checks role first, then case-insensitive name)."""
    responses = await jmap_client.request(
        token,
        api_url,
        MAIL_USING,
        [["Mailbox/get", {"accountId": account_id, "ids": None}, "mb0"]],
    )
    data = extract_response(responses, "mb0")
    mailboxes = data.get("list", [])

    lower = name_or_role.lower()
    for mb in mailboxes:
        if mb.get("role") == lower:
            return mb["id"]
    for mb in mailboxes:
        if (mb.get("name") or "").lower() == lower:
            return mb["id"]
    raise ToolError(f"No mailbox matching '{name_or_role}' found.")
