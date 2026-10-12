import json
import os
from typing import Literal

from dotenv import load_dotenv
from groq import Groq

from mcp_poc.tools.emergency_lookup import lookup_emergency_number


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(REPO_ROOT, ".env"))

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emergency_lookup",
        "description": (
            "Look up an emergency number. "
            "Country must be an ISO 3166-1 alpha-2 code such as JP or IN."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "ISO 3166-1 alpha-2 country code",
                },
                "service": {
                    "type": "string",
                    "enum": [
                        "police",
                        "ambulance",
                        "fire",
                        "general_emergency",
                    ],
                },
            },
            "required": ["country", "service"],
        },
    },
}


MODEL = "openai/gpt-oss-20b"


def main() -> None:
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

    # First Groq call: let the model decide whether to use the tool.
    response = groq_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[TOOL_SCHEMA],
        tool_choice="auto",
    )

    assistant_message = response.choices[0].message

    print("First call usage:", response.usage)

    print("Groq response:")
    print(assistant_message)

    if not assistant_message.tool_calls:
        print()
        print("Groq answered without calling a tool:")
        print(assistant_message.content)
        return

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
        print("Groq requested Python tool:", tool_name)
        print("Groq-generated arguments:", tool_arguments)

        # Direct in-process Python tool call.
        tool_result = lookup_emergency_number(
            country=tool_arguments["country"],
            service=tool_arguments["service"],
        )

        if tool_result is None:
            tool_output = (
                "No emergency number was found for the requested "
                "country and service."
            )
        else:
            tool_output = tool_result

        print("Python tool result:", tool_output)

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_output,
            }
        )

    # Second Groq call: generate the final answer from the tool result.
    final_response = groq_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[TOOL_SCHEMA],
        tool_choice="auto",
    )

    print("Second call usage:", final_response.usage)

    print()
    print("Final answer:")
    print(final_response.choices[0].message.content)


if __name__ == "__main__":
    main()