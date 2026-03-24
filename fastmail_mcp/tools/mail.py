"""Mail tools — JMAP session, mailboxes, email query & get, threads, attachments, stats (RFC 8621)."""

import json
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, get_account_id, jmap_client, resolve_download_url
from fastmail_mcp.dependencies import FastmailApiTokenDependency

from ._helpers import resolve_mailbox_by_name_or_role

MAIL_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"


def register(mcp: FastMCP):

    @mcp.tool()
    async def get_jmap_session(token: str = FastmailApiTokenDependency) -> dict[str, Any]:
        """Return the JMAP session: capabilities, account IDs, username, and feature availability.

        Use this to discover what features and scopes are available with your API token.
        """
        session = await jmap_client.get_session(token)
        return {
            "username": session.username,
            "api_url": session.api_url,
            "capabilities": sorted(session.capabilities.keys()),
            "accounts": {
                aid: {
                    "name": acc.name,
                    "is_personal": acc.is_personal,
                    "is_read_only": acc.is_read_only,
                    "capabilities": sorted(acc.account_capabilities.keys()),
                }
                for aid, acc in session.accounts.items()
            },
            "primary_accounts": session.primary_accounts,
        }

    # -- Mailboxes ---------------------------------------------------------------

    @mcp.tool()
    async def list_mailboxes(token: str = FastmailApiTokenDependency) -> list[dict[str, Any]]:
        """List all mailboxes (folders) in the account.

        Returns name, role (inbox/sent/drafts/trash/etc.), parent, email counts.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return [
            {
                "id": mb.get("id"),
                "name": mb.get("name"),
                "parentId": mb.get("parentId"),
                "role": mb.get("role"),
                "sortOrder": mb.get("sortOrder"),
                "totalEmails": mb.get("totalEmails"),
                "unreadEmails": mb.get("unreadEmails"),
                "totalThreads": mb.get("totalThreads"),
                "unreadThreads": mb.get("unreadThreads"),
            }
            for mb in data.get("list", [])
        ]

    @mcp.tool()
    async def create_mailbox(
        name: str,
        parent_id: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Create a new mailbox (folder).

        Args:
            name: Display name for the mailbox.
            parent_id: ID of the parent mailbox for nested folders (empty for top-level).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        create_obj: dict[str, Any] = {"name": name}
        if parent_id:
            create_obj["parentId"] = parent_id

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/set", {"accountId": account_id, "create": {"new0": create_obj}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "new0" not in created:
            err = data.get("notCreated", {}).get("new0", {})
            raise ToolError(
                f"Failed to create mailbox: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": created["new0"]["id"], "name": name}

    @mcp.tool()
    async def update_mailbox(
        mailbox_id: str,
        name: str = "",
        parent_id: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Update a mailbox (rename or move under a different parent).

        Args:
            mailbox_id: ID of the mailbox to update.
            name: New display name (empty to leave unchanged).
            parent_id: New parent mailbox ID (empty to leave unchanged; "null" moves to top-level).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        patch: dict[str, Any] = {}
        if name:
            patch["name"] = name
        if parent_id:
            patch["parentId"] = None if parent_id.lower() == "null" else parent_id
        if not patch:
            raise ToolError("Nothing to update — supply name or parent_id.")

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/set", {"accountId": account_id, "update": {mailbox_id: patch}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        if mailbox_id not in data.get("updated", {}):
            err = data.get("notUpdated", {}).get(mailbox_id, {})
            raise ToolError(
                f"Failed to update mailbox: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": mailbox_id, "updated": True}

    @mcp.tool()
    async def destroy_mailbox(
        mailbox_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Destroy (delete) a mailbox. Fails if the mailbox has children or is a system role."""
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/set", {"accountId": account_id, "destroy": [mailbox_id]}, "c0"]],
        )
        data = extract_response(responses, "c0")
        if mailbox_id not in data.get("destroyed", []):
            err = data.get("notDestroyed", {}).get(mailbox_id, {})
            raise ToolError(
                f"Failed to destroy mailbox: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": mailbox_id, "destroyed": True}

    # -- Email query & get -------------------------------------------------------

    @mcp.tool()
    async def query_emails(
        in_mailbox: str = "",
        text: str = "",
        from_addr: str = "",
        to_addr: str = "",
        subject: str = "",
        after: str = "",
        before: str = "",
        has_keyword: str = "",
        not_keyword: str = "",
        has_attachment: bool | None = None,
        filter_json: str = "",
        sort_property: str = "receivedAt",
        sort_ascending: bool = False,
        limit: int = 20,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Search for emails with structured filters. Returns matching emails with preview.

        Args:
            in_mailbox: Mailbox ID to search within.
            text: Full-text search across all fields (from, to, subject, body).
            from_addr: Filter by sender address or name.
            to_addr: Filter by recipient address or name.
            subject: Filter by subject text.
            after: Emails received after this date (ISO 8601, e.g. "2024-01-01T00:00:00Z").
            before: Emails received before this date (ISO 8601).
            has_keyword: Require keyword/flag ("$flagged", "$seen", "$draft", "$answered").
            not_keyword: Exclude emails with this keyword.
            has_attachment: Filter by attachment presence.
            filter_json: Raw JSON FilterCondition for complex queries (overrides other filter params).
            sort_property: Sort field — receivedAt, sentAt, from, to, subject, size.
            sort_ascending: Sort direction (default: newest first).
            limit: Max results (1–100, default 20).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        limit = max(1, min(limit, 100))

        filter_cond: dict[str, Any]
        if filter_json.strip():
            try:
                filter_cond = json.loads(filter_json)
            except json.JSONDecodeError as e:
                raise ToolError(f"Invalid filter_json: {e}") from e
        else:
            filter_cond = {}
            if in_mailbox:
                filter_cond["inMailbox"] = in_mailbox
            if text:
                filter_cond["text"] = text
            if from_addr:
                filter_cond["from"] = from_addr
            if to_addr:
                filter_cond["to"] = to_addr
            if subject:
                filter_cond["subject"] = subject
            if after:
                filter_cond["after"] = after
            if before:
                filter_cond["before"] = before
            if has_keyword:
                filter_cond["hasKeyword"] = has_keyword
            if not_keyword:
                filter_cond["notKeyword"] = not_keyword
            if has_attachment is not None:
                filter_cond["hasAttachment"] = has_attachment

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/query",
                    {
                        "accountId": account_id,
                        "filter": filter_cond,
                        "sort": [{"property": sort_property, "isAscending": sort_ascending}],
                        "limit": limit,
                    },
                    "q0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {
                            "resultOf": "q0",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "subject",
                            "receivedAt",
                            "sentAt",
                            "size",
                            "preview",
                            "keywords",
                        ],
                    },
                    "g0",
                ],
            ],
        )
        query_data = extract_response(responses, "q0")
        email_data = extract_response(responses, "g0")

        return {
            "total": query_data.get("total"),
            "position": query_data.get("position"),
            "emails": email_data.get("list", []),
        }

    @mcp.tool()
    async def get_emails(
        email_ids: str,
        fetch_body: bool = True,
        max_body_bytes: int = 10000,
        token: str = FastmailApiTokenDependency,
    ) -> list[dict[str, Any]]:
        """Get full details for one or more emails by ID.

        Args:
            email_ids: Comma-separated email IDs.
            fetch_body: Include text body content (default true).
            max_body_bytes: Max bytes per body part (default 10 000; protects LLM context).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        ids = [eid.strip() for eid in email_ids.split(",") if eid.strip()]
        if not ids:
            raise ToolError("No email IDs provided.")

        properties = [
            "id",
            "threadId",
            "mailboxIds",
            "from",
            "to",
            "cc",
            "bcc",
            "replyTo",
            "subject",
            "receivedAt",
            "sentAt",
            "size",
            "preview",
            "keywords",
            "textBody",
            "bodyValues",
        ]

        get_args: dict[str, Any] = {
            "accountId": account_id,
            "ids": ids,
            "properties": properties,
        }
        if fetch_body:
            get_args["fetchTextBodyValues"] = True
            get_args["maxBodyValueBytes"] = max(1, min(max_body_bytes, 50_000))

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/get", get_args, "c0"]],
        )
        data = extract_response(responses, "c0")
        return data.get("list", [])

    # -- Recent emails & threads -------------------------------------------------

    @mcp.tool()
    async def get_recent_emails(
        mailbox: str = "inbox",
        limit: int = 25,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get the most recent emails in a mailbox (sorted by date, newest first).

        Args:
            mailbox: Mailbox name or role (e.g. "inbox", "sent", "drafts", "trash", or a custom name).
            limit: Max results (1–50, default 25).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        limit = max(1, min(limit, 50))
        mailbox_id = await resolve_mailbox_by_name_or_role(
            token, session.api_url, account_id, mailbox
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/query",
                    {
                        "accountId": account_id,
                        "filter": {"inMailbox": mailbox_id},
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": limit,
                    },
                    "q0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {
                            "resultOf": "q0",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "subject",
                            "receivedAt",
                            "sentAt",
                            "size",
                            "preview",
                            "keywords",
                        ],
                    },
                    "g0",
                ],
            ],
        )
        query_data = extract_response(responses, "q0")
        email_data = extract_response(responses, "g0")
        return {
            "mailbox": mailbox,
            "total": query_data.get("total"),
            "emails": email_data.get("list", []),
        }

    @mcp.tool()
    async def get_thread(
        email_id: str = "",
        thread_id: str = "",
        max_body_bytes: int = 5000,
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get all emails in a conversation thread.

        Provide either an email_id (the thread is looked up automatically) or a thread_id directly.

        Args:
            email_id: An email ID whose thread to fetch.
            thread_id: A thread ID to fetch directly.
            max_body_bytes: Max bytes per body part (default 5000).
        """
        if not email_id and not thread_id:
            raise ToolError("Provide either email_id or thread_id.")

        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        if not thread_id:
            resp = await jmap_client.request(
                token,
                session.api_url,
                MAIL_USING,
                [
                    [
                        "Email/get",
                        {
                            "accountId": account_id,
                            "ids": [email_id],
                            "properties": ["threadId"],
                        },
                        "c0",
                    ]
                ],
            )
            data = extract_response(resp, "c0")
            emails = data.get("list", [])
            if not emails:
                raise ToolError(f"Email '{email_id}' not found.")
            thread_id = emails[0].get("threadId")
            if not thread_id:
                raise ToolError(f"No threadId on email '{email_id}'.")

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Thread/get",
                    {"accountId": account_id, "ids": [thread_id]},
                    "t0",
                ],
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "#ids": {
                            "resultOf": "t0",
                            "name": "Thread/get",
                            "path": "/list/*/emailIds",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "cc",
                            "subject",
                            "receivedAt",
                            "sentAt",
                            "size",
                            "preview",
                            "keywords",
                            "textBody",
                            "bodyValues",
                        ],
                        "fetchTextBodyValues": True,
                        "maxBodyValueBytes": max(1, min(max_body_bytes, 50_000)),
                    },
                    "g0",
                ],
            ],
        )
        thread_data = extract_response(responses, "t0")
        email_data = extract_response(responses, "g0")

        threads = thread_data.get("list", [])
        thread_email_ids: list[str] = threads[0].get("emailIds", []) if threads else []

        return {
            "threadId": thread_id,
            "emailIds": thread_email_ids,
            "emails": email_data.get("list", []),
        }

    # -- Attachments & stats -----------------------------------------------------

    @mcp.tool()
    async def get_email_attachments(
        email_id: str,
        token: str = FastmailApiTokenDependency,
    ) -> list[dict[str, Any]]:
        """List attachments on an email (metadata only — use download_attachment for content).

        Args:
            email_id: ID of the email.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "ids": [email_id],
                        "properties": ["attachments", "hasAttachment"],
                    },
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        emails = data.get("list", [])
        if not emails:
            raise ToolError(f"Email '{email_id}' not found.")

        return [
            {
                "blobId": att.get("blobId"),
                "name": att.get("name"),
                "type": att.get("type"),
                "size": att.get("size"),
                "charset": att.get("charset"),
                "disposition": att.get("disposition"),
            }
            for att in emails[0].get("attachments", [])
        ]

    @mcp.tool()
    async def download_attachment(
        blob_id: str,
        name: str = "attachment",
        content_type: str = "application/octet-stream",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get a download URL for an email attachment.

        Returns the fully-resolved URL only — does not write to the filesystem. Safe for hosted deployments.

        Args:
            blob_id: Blob ID of the attachment (from get_email_attachments).
            name: Filename for the download.
            content_type: MIME type for the download.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        url = resolve_download_url(
            session.download_url,
            account_id,
            blob_id,
            name=name,
            accept=content_type,
        )
        return {"downloadUrl": url, "blobId": blob_id, "name": name, "type": content_type}

    @mcp.tool()
    async def get_mailbox_stats(
        mailbox_id: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Get email count statistics for one or all mailboxes.

        Args:
            mailbox_id: Specific mailbox ID (empty for all mailboxes).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        get_args: dict[str, Any] = {"accountId": account_id}
        get_args["ids"] = [mailbox_id] if mailbox_id else None

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/get", get_args, "c0"]],
        )
        data = extract_response(responses, "c0")
        mailboxes = data.get("list", [])

        stats = [
            {
                "id": mb.get("id"),
                "name": mb.get("name"),
                "role": mb.get("role"),
                "totalEmails": mb.get("totalEmails", 0),
                "unreadEmails": mb.get("unreadEmails", 0),
                "totalThreads": mb.get("totalThreads", 0),
                "unreadThreads": mb.get("unreadThreads", 0),
            }
            for mb in mailboxes
        ]

        if mailbox_id and stats:
            return stats[0]
        return stats

    @mcp.tool()
    async def get_account_summary(
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Get an aggregate account summary: total emails, unread count, mailbox breakdown."""
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Mailbox/get", {"accountId": account_id, "ids": None}, "c0"]],
        )
        data = extract_response(responses, "c0")
        mailboxes = data.get("list", [])

        total_emails = sum(mb.get("totalEmails", 0) for mb in mailboxes)
        total_unread = sum(mb.get("unreadEmails", 0) for mb in mailboxes)
        total_threads = sum(mb.get("totalThreads", 0) for mb in mailboxes)

        top = sorted(mailboxes, key=lambda m: m.get("totalEmails", 0), reverse=True)[:10]

        return {
            "username": session.username,
            "mailboxCount": len(mailboxes),
            "totalEmails": total_emails,
            "totalUnread": total_unread,
            "totalThreads": total_threads,
            "topMailboxes": [
                {
                    "name": mb.get("name"),
                    "role": mb.get("role"),
                    "totalEmails": mb.get("totalEmails", 0),
                    "unreadEmails": mb.get("unreadEmails", 0),
                }
                for mb in top
            ],
        }
