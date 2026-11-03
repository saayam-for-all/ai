from mcp.server.mcpserver import MCPServer

from mcp_poc.tools.emergency_lookup import lookup_emergency_number
from typing import Literal

server = MCPServer(
    name="saayam-mcp-poc",
    description="Experimental MCP server for the Saayam MCP evaluation spike.",
)

@server.tool()
def emergency_lookup(
    country: str,
    service: Literal["police", "ambulance", "fire", "general_emergency"],
) -> str:
    """Look up an emergency number.

    Country must be an ISO 3166-1 alpha-2 code such as JP or IN.
    """
    result = lookup_emergency_number(country, service)

    if result is None:
        return "No emergency number was found for the requested country and service."

    return result

if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run_stdio_async())