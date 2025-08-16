import logging
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass
from uuid import uuid4

from .utils import call_llm
from .ctx import context
from .prompts import instructions as base_instructions
from .tool import ToolRegistry

@dataclass
class ExitGate:
    kind: str            # "shell" | "file_exists" | "none"
    expect: str          # "pass" | "fail" | "exists" | "not_exists"
    cmd: Optional[str] = None
    path: Optional[str] = None

class Node():
    def __init__(self):
        self._id: str = uuid4().hex
        self._name: str = ""
        self._routes: dict[str, str] = {}
        self._pre_func: dict[str, Any] = {}
        self._post_func: dict[str, Any] = {}
        self._base_instructions: str = base_instructions
        self._input: Optional[str] = None
        self._local_context: dict[str, str] = {}

        self._exit_gate: Optional[ExitGate] = None
        self._tool_subset: Optional[List[str]] = None
        self._cwd: Optional[str] = None
        self._max_round_trips: int = 8  # default higher than 6 to reduce 'budget exceeded'

    def __str__(self) -> str:
        return f"\nID: {self._id} Name: {self._name}"

    def context(self, local_context: dict[str, str]) -> 'Node':
        self._local_context = local_context
        return self

    def name(self, name: str) -> 'Node':
        self._name = name
        return self

    def input(self, input: str) -> 'Node':
        self._input = input
        return self

    def instructions(self, specifics: str) -> 'Node':
        self._base_instructions += f"\nSpecific instructions: {specifics}"
        return self

    def tools(self, tool_names: list[str]) -> 'Node':
        self._tool_subset = tool_names
        return self

    def exit(self, *, kind: str, expect: str, cmd: Optional[str] = None, path: Optional[str] = None) -> 'Node':
        self._exit_gate = ExitGate(kind=kind, expect=expect, cmd=cmd, path=path)
        return self

    def cwd(self, path: str) -> 'Node':
        self._cwd = path
        return self

    def budget(self, round_trips: int) -> 'Node':
        """Set per-node tool round-trip budget for call_llm."""
        self._max_round_trips = max(1, int(round_trips))
        return self

    def routes(self, routes: dict[str, str]) -> 'Node':
        self._routes = routes
        return self

    def pre(self, func: Callable, args: list | None = None) -> 'Node':
        self._pre_func = {"func": func, "args": args}
        return self

    def post(self, func: Callable, args: list | None = None) -> 'Node':
        self._post_func = {"func": func, "args": args}
        return self

    def _format_with_context(self, text: str) -> str:
        try:
            return text.format(**vars(context))
        except Exception:
            return text

    def execute(self):
        logging.info(f"Executing node: {self._name}")
        context.response_id = None

        prev_cwd = getattr(context, "cwd", None)
        if self._cwd:
            context.cwd = self._cwd

        if self._pre_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._pre_func.get("args", [])
            if args is None:
                self._pre_func['func']()
            else:
                self._pre_func['func'](*args)

        context_info = "\nContext (key: value)\n"
        keys_to_skip = ["next_node", "nodes", "running", "events", "client", "response_id", "paused"]
        for key, value in vars(context).items():
            if key in keys_to_skip:
                continue
            else:
                context_info += f"{key}: {value}\n"

        for key, value in self._local_context.items():
            context_info += f"{key}: {value}\n"

        instructions = self._base_instructions + context_info

        if self._exit_gate:
            if self._exit_gate.kind == "shell" and self._exit_gate.cmd:
                cmd = self._format_with_context(self._exit_gate.cmd)
                instructions += f"\nExit gate: run `{cmd}` and expect it to {self._exit_gate.expect}.\n"
            elif self._exit_gate.kind == "file_exists" and self._exit_gate.path:
                path = self._format_with_context(self._exit_gate.path)
                instructions += f"\nExit gate: ensure file {'exists' if self._exit_gate.expect=='exists' else 'does not exist'} at `{path}`.\n"

        route_info = ""
        for id in self._routes:
            node = next((n for n in context.nodes if n._id == id), None)
            if node:
                route_info += f"{node}: criteria: {self._routes.get(id)}\n"

        if len(self._routes) > 0:
            instructions += (
                f"\nThe current node is {self._name}. You must decide which node to route to "
                f"based on the following criteria (node, criteria):\n" + route_info +
                "\nYou must call the 'route' tool to route to the next node, along with your rationale.\n"
            )
        else:
            context.running = False

        tools = None
        if self._tool_subset is not None:
            allowed = list(self._tool_subset)
            from .tool import ToolRegistry
            if self._routes and "route" not in allowed and ToolRegistry.has_tool("route"):
                allowed.append("route")
            if ToolRegistry.has_tool("stop_request") and "stop_request" not in allowed:
                allowed.append("stop_request")
            tools = ToolRegistry.get_tools_subset(allowed)

        if self._input:
            call_llm(self._input, instructions=instructions, tools=tools, max_round_trips=self._max_round_trips)
        else:
            call_llm(input="Follow your instructions", instructions=instructions, tools=tools, max_round_trips=self._max_round_trips)

        if self._routes and getattr(context, "next_node", None) is None:
            logging.info("Route not chosen; enforcing route selection.")
            enforce_instructions = (
                "Now choose the next node. You must call the 'route' tool exactly once with "
                "next_node_id and rationale, and produce no other text.\n\n"
                "Candidates:\n" + route_info
            )
            from .tool import ToolRegistry
            if ToolRegistry.has_tool("route"):
                try:
                    call_llm(
                        input="",
                        instructions=enforce_instructions,
                        tools=ToolRegistry.get_tools_subset(["route"]),
                        tool_choice="required",
                        max_round_trips=2,
                    )
                except Exception as e:
                    logging.warning(f"Route enforcement failed: {e}")

        if self._post_func:
            logging.debug(f"Running post-function for node: {self._name}")
            args = self._post_func.get("args", [])
            if args is None:
                self._post_func['func']()
            else:
                self._post_func['func'](*args)

        if self._cwd is not None:
            if prev_cwd is None:
                try:
                    delattr(context, "cwd")
                except Exception:
                    pass
            else:
                context.cwd = prev_cwd
