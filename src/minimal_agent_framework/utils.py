from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
)
from typing import cast

import json
from typing import Callable, Type, Optional, Any
from .tool import ToolRegistry
from .ctx import context
from pydantic import BaseModel

class EventEmitter:
    def __init__(self):
        self._listeners = {}

    def on(self, event: str, callback: Callable):
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable):
        if event in self._listeners:
            self._listeners[event] = [cb for cb in self._listeners[event] if cb != callback]

    def emit(self, event: str, *args, **kwargs):
        if event in self._listeners:
            for callback in list(self._listeners[event]):
                callback(*args, **kwargs)

def _serialize_tool_output(result):
    if isinstance(result, (dict, list)):
        return json.dumps(result)
    return str(result)

def call_llm(
    input: str | list,
    instructions: Optional[str] = None,
    output: Optional[Type[BaseModel]] = None,
    tools: Optional[list[Any]] = None,
    tool_choice: Optional[Any] = None,
    max_round_trips: int = 6,
):
    """
    Stream text, handle function calls in discrete round-trips,
    and forward outputs back to the model until completion or budget exhausted.

    Interruptible with Ctrl+C:
    - On KeyboardInterrupt, sets context.paused = True and context.running = False
      and returns immediately so the host can open a model console.
    """

    # Normalize initial input
    if isinstance(input, str):
        input = [{"role": "user", "content": input}]

    # Build kwargs once
    kwargs = {}
    if output:
        kwargs["text_format"] = output
    if instructions:
        kwargs["instructions"] = instructions
    if tool_choice:
        kwargs["tool_choice"] = tool_choice

    round_trip = 0
    function_outputs = []  # carry function outputs between rounds

    while True:
        round_trip += 1
        if round_trip > max_round_trips:
            context.events.emit("error", f"Tool round-trip budget exceeded ({max_round_trips}).")
            break

        payload = input if round_trip == 1 else function_outputs

        context.events.emit("start", {"round": round_trip})

        tool_calls_this_round = []
        text_seen = False

        _tools = ToolRegistry.get_tools() if tools is None else tools

        try:
            with context.client.responses.stream(
                model=context.model,
                input=payload,
                tools=_tools,
                previous_response_id=context.response_id if getattr(context, "response_id", None) else None,
                **kwargs,
            ) as stream:
                try:
                    for event in stream:
                        et = event.type

                        if et == "response.created":
                            context.response_id = event.response.id

                        elif et == "response.output_text.delta":
                            text_seen = True
                            context.events.emit("text", event.delta)

                        elif et == "response.error":
                            context.events.emit("error", str(event.error))

                        elif et in ("response.output_item.done", "response.completed"):
                            # No-op here; final handled below
                            pass

                    # After the stream ends, inspect the final response for function calls
                    final: Response = stream.get_final_response()

                    for item in final.output:
                        if getattr(item, "type", None) == "function_call":
                            fcall = cast(ResponseFunctionToolCall, item)
                            try:
                                tool_result = ToolRegistry.call(fcall.name, fcall.arguments)
                                tool_calls_this_round.append({
                                    "type": "function_call_output",
                                    "call_id": fcall.call_id,
                                    "output": _serialize_tool_output(tool_result),
                                })
                                context.events.emit("tool_call", fcall.name)
                                context.events.emit("tool_result", {"name": fcall.name, "result": tool_result})
                            except Exception as e:
                                context.events.emit("error", f"Tool '{fcall.name}' failed: {e}")
                                tool_calls_this_round.append({
                                    "type": "function_call_output",
                                    "call_id": fcall.call_id,
                                    "output": _serialize_tool_output({"error": str(e)}),
                                })

                    context.events.emit("end", {"round": round_trip, "text_seen": text_seen})

                except KeyboardInterrupt:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    context.events.emit("error", "Interrupted by user (Ctrl+C). Pausing...")
                    context.paused = True
                    context.running = False
                    return  # leave immediately so host can open console

        except KeyboardInterrupt:
            context.events.emit("error", "Interrupted by user (Ctrl+C). Pausing...")
            context.paused = True
            context.running = False
            return
        except Exception as e:
            context.events.emit("error", f"Stream failed: {e}")
            break

        if not tool_calls_this_round:
            # No more function calls requested; we're done
            break

        # Prepare next round with the outputs of all tool calls
        function_outputs = tool_calls_this_round
