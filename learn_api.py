
import os
from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall
from dotenv import load_dotenv
from minimal_agent_framework.tool import tool, ToolRegistry


import logging
logging.basicConfig(level=logging.INFO)

load_dotenv()

@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b
  


api_key = os.getenv("AZURE_API_KEY")
base_url = os.getenv("AZURE_API_ENDPOINT")

client = OpenAI(api_key=api_key, base_url=base_url, default_query={"api-version": "preview"})

with client.responses.stream(
    input="hi - use the tools to add 43242 and 35252523",
    model="o4-mini",
    tools=ToolRegistry.get_tools(),
    ) as stream:
    for event in stream:
        if event.type == "response.output_item.done":
            tool_call = event.item
            if isinstance(tool_call, ResponseFunctionToolCall):
                tool_name = tool_call.name
                tool_args = tool_call.arguments
                logging.info(f"Tool called: {tool_name} with args: {tool_args}")
                output = ToolRegistry.call(tool_name, tool_args)
                print(f"Function output: {output}")
            

# rich.print(stream.get_final_response())

