import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(REPO_ROOT / ".env")

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])


server_params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_poc.server"],
    cwd=REPO_ROOT,
)


def build_groq_tools(tools_result) -> list[dict]:
    """Convert MCP tool definitions into Groq tool definitions."""
    groq_tools = []

    for tool in tools_result.tools:
        groq_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
        )

    return groq_tools


async def main() -> None:
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Discover tools from the MCP server.
            tools_result = await session.list_tools()
            groq_tools = build_groq_tools(tools_result)

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You answer questions using available tools when they "
                        "provide reliable information. Use the emergency lookup "
                        "tool when the question asks for an emergency number."
                    ),
                },
                {
                    "role": "user",
                    "content": "What is the emergency number for fire in Japan?",
                },
            ]

            response = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
            )

            assistant_message = response.choices[0].message

            print("First call usage:", response.usage)

            print("Groq response:")
            print(assistant_message)

            # If Groq decided to call an MCP tool, execute it.
            if assistant_message.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                },
                            }
                            for tool_call in assistant_message.tool_calls
                        ],
                    }
                )

                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_arguments = json.loads(tool_call.function.arguments)

                    print()
                    print("Groq requested MCP tool:", tool_name)
                    print("Groq-generated arguments:", tool_arguments)

                    # Call the tool through MCP.
                    tool_result = await session.call_tool(
                        tool_name,
                        arguments=tool_arguments,
                    )

                    print("MCP tool result:", tool_result)

                    # Extract the returned value to send back to Groq.
                    if tool_result.structured_content:
                        tool_output = json.dumps(tool_result.structured_content)
                    else:
                        tool_output = str(tool_result.content)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output,
                        }
                    )

                # Ask Groq for the final natural-language answer.
                final_response = groq_client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=messages,
                    tools=groq_tools,
                    tool_choice="auto",
                )

                print("Second call usage:", final_response.usage)

                print()
                print("Final answer:")
                print(final_response.choices[0].message.content)

            else:
                print()
                print("Groq answered without calling an MCP tool:")
                print(assistant_message.content)


if __name__ == "__main__":
    asyncio.run(main())