from pydantic import BaseModel
from openai.types.responses import ResponseFunctionToolCall
import json
from pydantic import BaseModel
import logging
from .tool import ToolRegistry
from typing import Callable
from .ctx import context


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

def call_llm(input: str | list, instructions: str | None = None, response_id: str | None = None, output: type[BaseModel] | None = None):
    """Call the OpenAI LLM with the provided input and return the response."""

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

    with context.client.responses.stream(
        input=input,
        model="o4-mini",
        tools=ToolRegistry.get_tools(),
        **kwargs
        ) as stream:
            tool_calls = []
            current_response_id = ""

            for event in stream:
                if event.type == "response.created":
                    current_response_id = event.response.id
                elif event.type == "response.output_text.delta":
                    context.events.emit("text", event.delta)
                elif event.type == "response.output_item.done":
                    tool_call = event.item
                    context.events.emit("tool_call", )
                    if isinstance(tool_call, ResponseFunctionToolCall):
                        tool_output = ToolRegistry.call(tool_call.name, tool_call.arguments)
                        tool_calls.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": json.dumps(tool_output) if isinstance(tool_output, dict) else str(tool_output)

                        })
            if len(tool_calls) > 0:           
                return call_llm(input=tool_calls, instructions=instructions, response_id=current_response_id, output=output)
    
