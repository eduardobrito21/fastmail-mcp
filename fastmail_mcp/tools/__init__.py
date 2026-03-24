from fastmcp import FastMCP

from .mail import register as register_mail
from .masked import register as register_masked
from .mutations import register as register_mutations
from .sieve import register as register_sieve
from .submission import register as register_submission
from .vacation import register as register_vacation


def register_tools(mcp: FastMCP):
    """Register all MCP tools."""
    register_mail(mcp)
    register_submission(mcp)
    register_mutations(mcp)
    register_masked(mcp)
    register_vacation(mcp)
    register_sieve(mcp)
