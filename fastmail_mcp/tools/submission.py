"""Submission tools — identities, send, draft lifecycle, reply (RFC 8621 / JMAP Submission)."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fastmail_mcp.client import extract_response, get_account_id, jmap_client
from fastmail_mcp.dependencies import FastmailApiTokenDependency

from ._helpers import MAIL_CAPABILITY, MAIL_USING, parse_addresses, resolve_mailbox_by_role

SUBMISSION_CAPABILITY = "urn:ietf:params:jmap:submission"
SUBMISSION_USING = [
    "urn:ietf:params:jmap:core",
    "urn:ietf:params:jmap:mail",
    SUBMISSION_CAPABILITY,
]


async def _resolve_identity(
    token: str,
    api_url: str,
    account_id: str,
    identity_id: str = "",
) -> dict[str, Any]:
    """Get a specific identity by ID, or the default (non-deletable / first)."""
    responses = await jmap_client.request(
        token,
        api_url,
        SUBMISSION_USING,
        [["Identity/get", {"accountId": account_id}, "id0"]],
    )
    data = extract_response(responses, "id0")
    identities: list[dict[str, Any]] = data.get("list", [])
    if not identities:
        raise ToolError("No sending identities found. Check your API token scopes.")

    if identity_id:
        for ident in identities:
            if ident.get("id") == identity_id:
                return ident
        raise ToolError(f"Identity '{identity_id}' not found.")

    for ident in identities:
        if not ident.get("mayDelete", True):
            return ident
    return identities[0]


def _build_email_object(
    *,
    mailbox_id: str,
    from_addr: list[dict[str, Any]] | None = None,
    to: list[dict[str, Any]] | None = None,
    cc: list[dict[str, Any]] | None = None,
    bcc: list[dict[str, Any]] | None = None,
    subject: str = "",
    text_body: str = "",
    html_body: str = "",
    keywords: dict[str, bool] | None = None,
    in_reply_to: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    """Build a JMAP Email create object."""
    email: dict[str, Any] = {
        "mailboxIds": {mailbox_id: True},
        "subject": subject,
        "keywords": keywords or {"$seen": True},
    }
    if from_addr:
        email["from"] = from_addr
    if to:
        email["to"] = to
    if cc:
        email["cc"] = cc
    if bcc:
        email["bcc"] = bcc
    if in_reply_to:
        email["inReplyTo"] = in_reply_to
    if references:
        email["references"] = references

    body_values: dict[str, Any] = {}
    if text_body and html_body:
        email["textBody"] = [{"partId": "text", "type": "text/plain"}]
        email["htmlBody"] = [{"partId": "html", "type": "text/html"}]
        body_values["text"] = {"value": text_body}
        body_values["html"] = {"value": html_body}
    elif html_body:
        email["htmlBody"] = [{"partId": "html", "type": "text/html"}]
        body_values["html"] = {"value": html_body}
    else:
        email["textBody"] = [{"partId": "text", "type": "text/plain"}]
        body_values["text"] = {"value": text_body}

    email["bodyValues"] = body_values
    return email


def register(mcp: FastMCP):

    # -- Identities --------------------------------------------------------------

    @mcp.tool()
    async def list_identities(
        token: str = FastmailApiTokenDependency,
    ) -> list[dict[str, Any]]:
        """List sending identities (email addresses you can send from).

        Requires the ``urn:ietf:params:jmap:submission`` scope.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, SUBMISSION_CAPABILITY)

        responses = await jmap_client.request(
            token,
            session.api_url,
            SUBMISSION_USING,
            [["Identity/get", {"accountId": account_id}, "c0"]],
        )
        data = extract_response(responses, "c0")
        return [
            {
                "id": ident.get("id"),
                "name": ident.get("name"),
                "email": ident.get("email"),
                "replyTo": ident.get("replyTo"),
                "bcc": ident.get("bcc"),
                "htmlSignature": ident.get("htmlSignature"),
                "textSignature": ident.get("textSignature"),
                "mayDelete": ident.get("mayDelete"),
            }
            for ident in data.get("list", [])
        ]

    # -- Send --------------------------------------------------------------------

    @mcp.tool()
    async def send_email(
        to: str,
        subject: str,
        text_body: str = "",
        html_body: str = "",
        cc: str = "",
        bcc: str = "",
        identity_id: str = "",
        in_reply_to: str = "",
        references: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Compose and send an email immediately.

        Args:
            to: Recipients (comma-separated, e.g. "user@example.com, Name <other@example.com>").
            subject: Email subject line.
            text_body: Plain-text body content.
            html_body: HTML body content (optional; both text and HTML can be provided).
            cc: CC recipients (comma-separated, same format as to).
            bcc: BCC recipients (comma-separated, same format as to).
            identity_id: Sending identity ID (use list_identities to see options; empty for default).
            in_reply_to: Message-ID of the email being replied to.
            references: Space-separated Message-IDs for the References header.
        """
        if not text_body and not html_body:
            raise ToolError("Provide at least one of text_body or html_body.")
        to_addrs = parse_addresses(to)
        if not to_addrs:
            raise ToolError("At least one 'to' address is required.")

        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, SUBMISSION_CAPABILITY)

        identity = await _resolve_identity(token, session.api_url, account_id, identity_id)
        from_addr = [{"name": identity.get("name"), "email": identity.get("email")}]

        drafts_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "drafts")
        sent_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "sent")

        email_obj = _build_email_object(
            mailbox_id=drafts_id,
            from_addr=from_addr,
            to=to_addrs,
            cc=parse_addresses(cc) if cc else None,
            bcc=parse_addresses(bcc) if bcc else None,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            keywords={"$seen": True, "$draft": True},
            in_reply_to=[in_reply_to] if in_reply_to else None,
            references=references.split() if references else None,
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            SUBMISSION_USING,
            [
                [
                    "Email/set",
                    {"accountId": account_id, "create": {"draft": email_obj}},
                    "c0",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": account_id,
                        "create": {
                            "sub0": {
                                "identityId": identity["id"],
                                "emailId": "#draft",
                            },
                        },
                        "onSuccessUpdateEmail": {
                            "#sub0": {
                                f"mailboxIds/{drafts_id}": None,
                                f"mailboxIds/{sent_id}": True,
                                "keywords/$draft": None,
                            },
                        },
                    },
                    "c1",
                ],
            ],
        )

        email_data = extract_response(responses, "c0")
        created = email_data.get("created", {})
        if "draft" not in created:
            err = email_data.get("notCreated", {}).get("draft", {})
            raise ToolError(
                f"Failed to create email: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )

        sub_data = extract_response(responses, "c1")
        sub_created = sub_data.get("created", {})
        if "sub0" not in sub_created:
            err = sub_data.get("notCreated", {}).get("sub0", {})
            raise ToolError(
                f"Failed to submit email: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )

        return {
            "emailId": created["draft"]["id"],
            "submissionId": sub_created["sub0"]["id"],
            "sent": True,
        }

    # -- Draft lifecycle ---------------------------------------------------------

    @mcp.tool()
    async def create_draft(
        to: str = "",
        subject: str = "",
        text_body: str = "",
        html_body: str = "",
        cc: str = "",
        bcc: str = "",
        in_reply_to: str = "",
        references: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Save a new email as a draft (not sent).

        At least one of to, subject, or a body field should be provided.

        Args:
            to: Recipients (comma-separated).
            subject: Email subject line.
            text_body: Plain-text body content.
            html_body: HTML body content.
            cc: CC recipients (comma-separated).
            bcc: BCC recipients (comma-separated).
            in_reply_to: Message-ID being replied to.
            references: Space-separated Message-IDs for References header.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        drafts_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "drafts")

        from_addr: list[dict[str, Any]] = []
        try:
            identity = await _resolve_identity(token, session.api_url, account_id)
            from_addr = [{"name": identity.get("name"), "email": identity.get("email")}]
        except ToolError:
            pass

        email_obj = _build_email_object(
            mailbox_id=drafts_id,
            from_addr=from_addr or None,
            to=parse_addresses(to) if to else None,
            cc=parse_addresses(cc) if cc else None,
            bcc=parse_addresses(bcc) if bcc else None,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            keywords={"$draft": True},
            in_reply_to=[in_reply_to] if in_reply_to else None,
            references=references.split() if references else None,
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "create": {"draft": email_obj}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "draft" not in created:
            err = data.get("notCreated", {}).get("draft", {})
            raise ToolError(
                f"Failed to create draft: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": created["draft"]["id"], "isDraft": True}

    @mcp.tool()
    async def edit_draft(
        draft_id: str,
        to: str = "",
        subject: str = "",
        text_body: str = "",
        html_body: str = "",
        cc: str = "",
        bcc: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Replace a draft with updated content.

        JMAP emails are immutable — this creates a new draft and destroys the old one atomically.
        Empty fields keep the original value.

        Args:
            draft_id: ID of the existing draft to replace.
            to: Recipients (comma-separated). Empty keeps original.
            subject: Email subject. Empty keeps original.
            text_body: Plain-text body. Empty keeps original.
            html_body: HTML body. Empty keeps original.
            cc: CC recipients. Empty keeps original.
            bcc: BCC recipients. Empty keeps original.
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        get_responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "ids": [draft_id],
                        "properties": [
                            "mailboxIds",
                            "from",
                            "to",
                            "cc",
                            "bcc",
                            "subject",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                            "keywords",
                            "inReplyTo",
                            "references",
                        ],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "c0",
                ]
            ],
        )
        get_data = extract_response(get_responses, "c0")
        originals = get_data.get("list", [])
        if not originals:
            raise ToolError(f"Draft '{draft_id}' not found.")
        original = originals[0]

        mailbox_ids: dict[str, bool] = original.get("mailboxIds", {})
        mailbox_id = next(iter(mailbox_ids), None)
        if not mailbox_id:
            mailbox_id = await resolve_mailbox_by_role(
                token, session.api_url, account_id, "drafts"
            )

        body_values = original.get("bodyValues", {})
        orig_text = ""
        for part in original.get("textBody", []):
            pid = part.get("partId")
            if pid and pid in body_values:
                orig_text = body_values[pid].get("value", "")
                break
        orig_html = ""
        for part in original.get("htmlBody", []):
            pid = part.get("partId")
            if pid and pid in body_values:
                orig_html = body_values[pid].get("value", "")
                break

        email_obj = _build_email_object(
            mailbox_id=mailbox_id,
            from_addr=original.get("from"),
            to=parse_addresses(to) if to else original.get("to"),
            cc=parse_addresses(cc) if cc else original.get("cc"),
            bcc=parse_addresses(bcc) if bcc else original.get("bcc"),
            subject=subject or original.get("subject", ""),
            text_body=text_body or orig_text,
            html_body=html_body or orig_html,
            keywords=original.get("keywords", {"$draft": True}),
            in_reply_to=original.get("inReplyTo"),
            references=original.get("references"),
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/set",
                    {
                        "accountId": account_id,
                        "create": {"newDraft": email_obj},
                        "destroy": [draft_id],
                    },
                    "c0",
                ]
            ],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "newDraft" not in created:
            err = data.get("notCreated", {}).get("newDraft", {})
            raise ToolError(
                f"Failed to create replacement draft: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": created["newDraft"]["id"], "replacedDraftId": draft_id}

    @mcp.tool()
    async def send_draft(
        draft_id: str,
        identity_id: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Send an existing draft email.

        Args:
            draft_id: ID of the draft to send.
            identity_id: Sending identity ID (empty for default).
        """
        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, SUBMISSION_CAPABILITY)

        identity = await _resolve_identity(token, session.api_url, account_id, identity_id)
        drafts_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "drafts")
        sent_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "sent")

        responses = await jmap_client.request(
            token,
            session.api_url,
            SUBMISSION_USING,
            [
                [
                    "EmailSubmission/set",
                    {
                        "accountId": account_id,
                        "create": {
                            "sub0": {
                                "identityId": identity["id"],
                                "emailId": draft_id,
                            },
                        },
                        "onSuccessUpdateEmail": {
                            "#sub0": {
                                f"mailboxIds/{drafts_id}": None,
                                f"mailboxIds/{sent_id}": True,
                                "keywords/$draft": None,
                            },
                        },
                    },
                    "c0",
                ],
            ],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "sub0" not in created:
            err = data.get("notCreated", {}).get("sub0", {})
            raise ToolError(
                f"Failed to send draft: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {
            "submissionId": created["sub0"]["id"],
            "emailId": draft_id,
            "sent": True,
        }

    # -- Reply -------------------------------------------------------------------

    @mcp.tool()
    async def reply_email(
        email_id: str,
        text_body: str = "",
        html_body: str = "",
        reply_all: bool = False,
        send: bool = True,
        identity_id: str = "",
        token: str = FastmailApiTokenDependency,
    ) -> dict[str, Any]:
        """Reply to an email. Sends immediately by default; set send=false to save as draft.

        Builds Re: subject, In-Reply-To, and References headers automatically.

        Args:
            email_id: ID of the email to reply to.
            text_body: Plain-text reply body.
            html_body: HTML reply body.
            reply_all: If true, reply to all original recipients (not just sender).
            send: If true (default), send immediately; if false, save as draft.
            identity_id: Sending identity ID (empty for default).
        """
        if not text_body and not html_body:
            raise ToolError("Provide at least one of text_body or html_body.")

        session = await jmap_client.get_session(token)
        account_id = get_account_id(session, MAIL_CAPABILITY)

        get_responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [
                [
                    "Email/get",
                    {
                        "accountId": account_id,
                        "ids": [email_id],
                        "properties": [
                            "from",
                            "to",
                            "cc",
                            "replyTo",
                            "subject",
                            "messageId",
                            "references",
                        ],
                    },
                    "c0",
                ]
            ],
        )
        get_data = extract_response(get_responses, "c0")
        originals = get_data.get("list", [])
        if not originals:
            raise ToolError(f"Email '{email_id}' not found.")
        original = originals[0]

        orig_message_ids: list[str] = original.get("messageId") or []
        orig_references: list[str] = original.get("references") or []
        reply_references = orig_references + orig_message_ids

        orig_subject = original.get("subject", "")
        reply_subject = (
            orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        )

        reply_to_addrs: list[dict[str, Any]] = original.get("replyTo") or original.get("from", [])

        identity = await _resolve_identity(token, session.api_url, account_id, identity_id)
        from_addr = [{"name": identity.get("name"), "email": identity.get("email")}]
        my_email = (identity.get("email") or "").lower()

        cc_addrs: list[dict[str, Any]] | None = None
        if reply_all:
            orig_to: list[dict[str, Any]] = original.get("to") or []
            orig_cc: list[dict[str, Any]] = original.get("cc") or []
            all_recips = orig_to + orig_cc
            reply_emails: set[str] = {
                (a.get("email") or "").lower() for a in reply_to_addrs
            }
            exclude = reply_emails | {my_email}
            cc_addrs = [
                a for a in all_recips if (a.get("email") or "").lower() not in exclude
            ]
            if not cc_addrs:
                cc_addrs = None

        if send:
            drafts_id = await resolve_mailbox_by_role(
                token, session.api_url, account_id, "drafts"
            )
            sent_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "sent")

            email_obj = _build_email_object(
                mailbox_id=drafts_id,
                from_addr=from_addr,
                to=reply_to_addrs,
                cc=cc_addrs,
                subject=reply_subject,
                text_body=text_body,
                html_body=html_body,
                keywords={"$seen": True, "$draft": True},
                in_reply_to=orig_message_ids,
                references=reply_references,
            )

            responses = await jmap_client.request(
                token,
                session.api_url,
                SUBMISSION_USING,
                [
                    [
                        "Email/set",
                        {"accountId": account_id, "create": {"reply": email_obj}},
                        "c0",
                    ],
                    [
                        "EmailSubmission/set",
                        {
                            "accountId": account_id,
                            "create": {
                                "sub0": {
                                    "identityId": identity["id"],
                                    "emailId": "#reply",
                                },
                            },
                            "onSuccessUpdateEmail": {
                                "#sub0": {
                                    f"mailboxIds/{drafts_id}": None,
                                    f"mailboxIds/{sent_id}": True,
                                    "keywords/$draft": None,
                                },
                            },
                        },
                        "c1",
                    ],
                    [
                        "Email/set",
                        {
                            "accountId": account_id,
                            "update": {email_id: {"keywords/$answered": True}},
                        },
                        "c2",
                    ],
                ],
            )

            email_data = extract_response(responses, "c0")
            created = email_data.get("created", {})
            if "reply" not in created:
                err = email_data.get("notCreated", {}).get("reply", {})
                raise ToolError(
                    f"Failed to create reply: {err.get('type', 'unknown')} — {err.get('description', '')}"
                )

            sub_data = extract_response(responses, "c1")
            sub_created = sub_data.get("created", {})
            if "sub0" not in sub_created:
                err = sub_data.get("notCreated", {}).get("sub0", {})
                raise ToolError(
                    f"Failed to submit reply: {err.get('type', 'unknown')} — {err.get('description', '')}"
                )

            return {
                "emailId": created["reply"]["id"],
                "submissionId": sub_created["sub0"]["id"],
                "sent": True,
                "inReplyTo": email_id,
            }

        # Save as draft only
        drafts_id = await resolve_mailbox_by_role(token, session.api_url, account_id, "drafts")
        email_obj = _build_email_object(
            mailbox_id=drafts_id,
            from_addr=from_addr,
            to=reply_to_addrs,
            cc=cc_addrs,
            subject=reply_subject,
            text_body=text_body,
            html_body=html_body,
            keywords={"$draft": True},
            in_reply_to=orig_message_ids,
            references=reply_references,
        )

        responses = await jmap_client.request(
            token,
            session.api_url,
            MAIL_USING,
            [["Email/set", {"accountId": account_id, "create": {"reply": email_obj}}, "c0"]],
        )
        data = extract_response(responses, "c0")
        created = data.get("created", {})
        if "reply" not in created:
            err = data.get("notCreated", {}).get("reply", {})
            raise ToolError(
                f"Failed to create reply draft: {err.get('type', 'unknown')} — {err.get('description', '')}"
            )
        return {"id": created["reply"]["id"], "isDraft": True, "inReplyTo": email_id}
