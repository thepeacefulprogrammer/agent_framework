from openai import OpenAI
from pydantic import BaseModel
import os
from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall, ParsedResponse
import json
from pydantic import BaseModel
import logging
from minimal_agent_framework.tool import ToolRegistry
from typing import Callable

class EventEmitter:
    def __init__(self):
        self._listeners = {}

    def on(self, event: str, callback: Callable):
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(callback)

    def emit(self, event: str, *args, **kwargs):
        if event in self._listeners:
            for callback in self._listeners[event]:
                callback(*args, **kwargs)

def call_llm(input: str | list, instructions: str | None = None, response_id: str | None = None, output: type[BaseModel] | None = None, events: EventEmitter | None = None):
    """Call the OpenAI LLM with the provided input and return the response."""

    api_key = os.getenv("AZURE_API_KEY")
    base_url = os.getenv("AZURE_API_ENDPOINT")

    client = OpenAI(api_key=api_key, base_url=base_url, default_query={"api-version": "preview"})

    if isinstance(input, str):
        input = [{
            "role": "user", 
            "content": input,
        }]

    kwargs = {}
    if response_id:
        kwargs['previous_response_id'] = response_id
    if output:
        kwargs['text_format'] = output
    if instructions:
        kwargs['instructions'] = instructions

    logging.debug(f"Calling LLM with input: {input} and response_id: {response_id}")

    with client.responses.stream(
        input=input,
        model="o4-mini",
        tools=ToolRegistry.get_tools(),
        **kwargs
        ) as stream:
            tool_calls = []
            previous_response_id = ""

            for event in stream:
                if event.type == "response.created":
                    previous_response_id = event.response.id
                elif event.type == "response.output_text.delta" and events:
                    events.emit("text", event.delta)
                elif event.type == "response.output_item.done":
                    tool_call = event.item
                    if isinstance(tool_call, ResponseFunctionToolCall):
                        tool_output = ToolRegistry.call(tool_call.name, tool_call.arguments)
                        tool_calls.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": json.dumps(tool_output) if isinstance(tool_output, dict) else str(tool_output)

                        })
            if len(tool_calls) > 0:
                return call_llm(tool_calls, previous_response_id, output=output, events=events)
        
    return stream.get_final_response().output_parsed