import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]

server_params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_poc.server"],
    cwd=REPO_ROOT,
)


async def main() -> None:
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools_result = await session.list_tools()

            print("Discovered tools:")
            for tool in tools_result.tools:
                print()
                print("Name:", tool.name)
                print("Description:", tool.description)
                print("Input schema:", tool.input_schema)
                print("Output schema:", tool.output_schema)

            tool_result = await session.call_tool(
                "emergency_lookup",
                arguments={
                    "country": "JP",
                    "service": "fire",
                },
            )

            print()
            print("Invocation result:")
            print(tool_result)

if __name__ == "__main__":
    asyncio.run(main())