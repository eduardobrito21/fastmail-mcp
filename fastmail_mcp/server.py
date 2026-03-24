from fastmcp import FastMCP

from fastmail_mcp.tools import register_tools

mcp = FastMCP(
    name="fastmail-mcp",
    instructions=(
        "Tools for Fastmail via JMAP — mail (query, read, send, reply, draft lifecycle, "
        "mutations, threads, attachments), masked email, vacation, and Sieve scripts."
    ),
)

register_tools(mcp)


def main():
    """MCP over stdio (e.g. Cursor)."""
    mcp.run()


def main_http():
    """MCP over HTTP (e.g. hosted; token via ``X-Fastmail-Api-Token`` or query)."""
    mcp.run(transport="http")
