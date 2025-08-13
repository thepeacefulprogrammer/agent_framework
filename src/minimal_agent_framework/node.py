import logging
from typing import Optional, Callable, Any
from .utils import call_llm
from .ctx import context
from .prompts import instructions as base_instructions
from uuid import uuid4
from .tool import ToolRegistry

class Node():
    def __init__(self):
        self._id: str = uuid4().hex
        self._name = ""
        self._routes: dict[str, str] = {}
        self._pre_func: dict[str, Any] = {}
        self._post_func: dict[str, Any] = {}
        self._base_instructions: str = base_instructions
        self._input: Optional[str] = None
        self._local_context: dict[str, str] = {}

    def __str__(self) -> str:
        return f"\nID: {self._id} Name: {self._name}"

    def context(self, local_context: dict[str, str]) -> 'Node':
        """Set a context variable only for this node"""
        self._local_context = local_context
        return self

    def name(self, name: str) -> 'Node':
        self._name: str = name
        return self

    def input(self, input: str) -> 'Node':
        self._input = input
        return self

    def instructions(self, specifics: str) -> 'Node':
        self._base_instructions += f"\nSpecific instructions: {specifics}"
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
    
    def execute(self):
        logging.info(f"Executing node: {self._name}")
        context.response_id = None

        if self._pre_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._pre_func.get("args", [])
            if args is None:
                self._pre_func['func']()
            else:
                self._pre_func['func'](*args)

        context_info = "\nContext (key: value)\n"
        keys_to_skip = ["next_node", "nodes", "running", "events", "client", "response_id"]
        for key, value in vars(context).items():
            if key in keys_to_skip:
                continue
            else:
                context_info += f"{key}: {value}\n"

        for key, value in self._local_context.items():
            context_info += f"{key}: {value}\n"

        instructions = self._base_instructions + context_info
        
        route_info = ""
        for id in self._routes:
            node = next((n for n in context.nodes if n._id == id), None)
            if node:
                route_info += f"{node}: criteria: {self._routes.get(id)}\n"

        if len(self._routes) > 0:
            instructions += f"\nThe current node is {self._name}. You must decide which node to route to based on the following criteria (node, criteria):\n" + route_info + "\nYou must the route tool to route to the next node, along with your rationale for routing to that node.\n"
        else:
            context.running = False

        if self._input:
            call_llm(self._input, instructions=instructions)
        else:
            call_llm(input="Follow your instructions", instructions=instructions)

        if self._routes and getattr(context, "next_node", None) is None:
            logging.info("Route not chosen; enforcing route selection.")
            enforce_instructions = (
                "Now choose the next node. You must call the 'route' tool exactly once with "
                "next_node_id and rationale, and produce no other text.\n\n"
                "Candidates:\n" + route_info
            )
            if ToolRegistry.has_tool("route"):
                try:
                    call_llm(
                        input="",
                        instructions=enforce_instructions,
                        tools=ToolRegistry.get_tools_subset(["route"]),
                        tool_choice="required",
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