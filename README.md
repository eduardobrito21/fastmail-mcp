# fastmail-mcp

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for **Fastmail** built with [FastMCP](https://github.com/jlowin/fastmcp), [httpx](https://www.python-httpx.org/), and [Pydantic](https://docs.pydantic.dev/).

Communicates with Fastmail via [JMAP](https://jmap.io/) (RFC 8620 / 8621) — no IMAP, no Node, no forks.

## Features

| Area | Tools | JMAP methods |
|---|---|---|
| **Session** | `get_jmap_session` | `GET /jmap/session` |
| **Mailboxes** | `list_mailboxes`, `create_mailbox`, `update_mailbox`, `destroy_mailbox` | `Mailbox/get`, `Mailbox/set` |
| **Email (read)** | `query_emails`, `get_emails`, `get_recent_emails`, `get_thread` | `Email/query`, `Email/get`, `Thread/get` |
| **Submission** | `list_identities`, `send_email`, `create_draft`, `edit_draft`, `send_draft`, `reply_email` | `Identity/get`, `Email/set`, `EmailSubmission/set` |
| **Mutations** | `mark_email_read`, `pin_email`, `delete_email`, `move_email`, `add_labels`, `remove_labels` | `Email/set` |
| **Bulk mutations** | `bulk_mark_read`, `bulk_pin`, `bulk_delete`, `bulk_move`, `bulk_add_labels`, `bulk_remove_labels` | `Email/set` (batch) |
| **Attachments & stats** | `get_email_attachments`, `download_attachment`, `get_mailbox_stats`, `get_account_summary` | `Email/get`, `Mailbox/get` |
| **Masked Email** | `list_masked_emails`, `create_masked_email`, `update_masked_email`, `destroy_masked_email` | `MaskedEmail/get`, `MaskedEmail/set` |
| **Vacation** | `get_vacation_response`, `set_vacation_response` | `VacationResponse/get`, `VacationResponse/set` |
| **Sieve Scripts** | `list_sieve_scripts`, `get_sieve_script`, `create_sieve_script`, `update_sieve_script`, `destroy_sieve_script`, `validate_sieve_script` | `SieveScript/get`, `SieveScript/set`, `SieveScript/validate` |

## Setup

### 1. Create a Fastmail API token

1. Go to **[Fastmail → Settings → Privacy & Security → Integrations → API tokens](https://app.fastmail.com/settings/security/tokens)** (or see [Fastmail developer docs](https://www.fastmail.com/dev/)).
2. Create a new API token with the scopes you need:

| Scope | Required for |
|---|---|
| `urn:ietf:params:jmap:core` | All tools (session discovery) |
| `urn:ietf:params:jmap:mail` | Mailboxes, email read/query, mutations, threads, attachments, stats |
| `urn:ietf:params:jmap:submission` | Sending email, draft lifecycle, reply, identities (`list_identities`, `send_email`, `send_draft`, `reply_email`) |
| `https://www.fastmail.com/dev/maskedemail` | Masked email tools |
| `urn:ietf:params:jmap:vacationresponse` | Vacation response tools |
| `urn:ietf:params:jmap:sieve` | Sieve script tools (if available — see [Filters & Rules note](#filters--rules-web-ui)) |

### 2. Environment variables

Copy `.env.example` to `.env` and fill in your token:

```bash
# Required
FASTMAIL_API_TOKEN=fmu1-...

# Optional — override the JMAP session URL (default: Fastmail production)
# FASTMAIL_JMAP_SESSION_URL=https://api.fastmail.com/jmap/session

# HTTP transport only — see "Deployment" section
# FASTMAIL_MCP_HTTP_ALLOW_ENV_API_KEY=false
```

## Usage

### Local (stdio) — Cursor, Claude Desktop, etc.

Install from the repo (or a built wheel):

```bash
uv pip install -e .
```

Run the MCP server over stdio:

```bash
fastmail-mcp
```

#### Cursor configuration

Add to your Cursor MCP settings (`.cursor/mcp.json` or global):

```json
{
  "mcpServers": {
    "fastmail": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fastmail-mcp", "fastmail-mcp"],
      "env": {
        "FASTMAIL_API_TOKEN": "fmu1-..."
      }
    }
  }
}
```

#### Claude Desktop configuration

```json
{
  "mcpServers": {
    "fastmail": {
      "command": "/path/to/fastmail-mcp/.venv/bin/fastmail-mcp",
      "env": {
        "FASTMAIL_API_TOKEN": "fmu1-..."
      }
    }
  }
}
```

### Remote (HTTP) — hosted server

Start the HTTP transport:

```bash
fastmail-mcp-http
```

Callers authenticate per-request via:

- **Header** (preferred): `X-Fastmail-Api-Token: fmu1-...`
- **Query parameter**: `?fastmail_api_token=fmu1-...`

Connect from Cursor or Claude Desktop using [`mcp-remote`](https://github.com/geelen/mcp-remote):

```json
{
  "mcpServers": {
    "fastmail": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://your-host.example.com/mcp",
        "--header",
        "X-Fastmail-Api-Token: fmu1-..."
      ]
    }
  }
}
```

## Sending email

The `send_email`, `reply_email`, and `send_draft` tools require a token with the `urn:ietf:params:jmap:submission` scope in addition to `urn:ietf:params:jmap:mail`.

Typical flow:

1. **List identities** — `list_identities` shows which "from" addresses are available.
2. **Send directly** — `send_email` composes and sends in one step (creates the email + submission as a single JMAP batch).
3. **Draft workflow** — `create_draft` → `edit_draft` (optional, can repeat) → `send_draft`.
4. **Reply** — `reply_email` automatically builds `Re:` subject, `In-Reply-To`, and `References` headers. Use `reply_all=true` to include all original recipients.

JMAP emails are immutable — `edit_draft` atomically creates a new draft and destroys the old one.

## Deployment

- **Never store a shared user token in server environment** on a hosted deployment. Set `FASTMAIL_MCP_HTTP_ALLOW_ENV_API_KEY=false` (the default) so the server always requires callers to send their own token via header or query parameter.
- **Never log tokens.** The server uses `SecretStr` for the env token and never writes it to stdout/stderr.
- **Never log message bodies or email addresses.** Error messages from JMAP are surfaced but the server does not log email content.
- `download_attachment` returns a URL only — it does not write files to the server filesystem, making it safe for hosted deployments.
- For single-user local setups, `FASTMAIL_API_TOKEN` in the process env is fine — it's only read when running over stdio, or when `FASTMAIL_MCP_HTTP_ALLOW_ENV_API_KEY=true`.

## Filters & Rules (web UI)

Fastmail's **Settings → Filters & Rules** (move-to-mailbox rules, snooze actions, blocked senders, etc.) are configured through the web UI. These rules are **not** part of the standard JMAP API exposed to API tokens.

- If the JMAP session advertises `urn:ietf:params:jmap:sieve` (RFC 9661), the Sieve script tools in this server can list, create, and manage server-side Sieve filter scripts.
- If the capability is **absent**, the Sieve tools will return a clear error message. In that case, manage your filters at **<https://app.fastmail.com/settings/rules>**.
- Snooze-specific actions and UI-only rule types are not available via any public API.

## Development

```bash
# Clone and install
git clone https://github.com/your-user/fastmail-mcp.git
cd fastmail-mcp
uv sync

# Run locally
uv run fastmail-mcp

# Lint
uv run ruff check .
uv run basedpyright
```

## Links

- [Fastmail developer docs](https://www.fastmail.com/dev/)
- [JMAP specification (RFC 8620)](https://www.rfc-editor.org/rfc/rfc8620)
- [JMAP Mail (RFC 8621)](https://www.rfc-editor.org/rfc/rfc8621)
- [JMAP for Sieve Scripts (RFC 9661)](https://www.rfc-editor.org/rfc/rfc9661)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
