import logging
from typing import Optional, Callable, Any
from .utils import EventEmitter, call_llm
import json
from .ctx import context
from pydantic import BaseModel
from uuid import uuid4

class Node(BaseModel):
    def __init__(self):
        self._id: str = uuid4().hex
        self._name = ""
        self._routes: dict[str, str] = {}
        self._pre_func: dict[str, Any] = {}
        self._post_func: dict[str, Any] = {}
        self._instructions: Optional[str] = None
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

    def instructions(self, instructions: str) -> 'Node':
        self._instructions = instructions
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

        if not self._instructions:
                self._instructions = ""

        context_info = "\nContext (key: value)\n"
        for key, value in vars(context).items():
            if key == "next_node" or key == "nodes" or key == "running":
                continue
            else:
                context_info += f"{key}: {value}\n"

        for key, value in self._local_context.items():
            context_info += f"{key}: {value}"


        self._instructions += context_info
        
        if self._pre_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._pre_func.get("args", [])
            if args is None:
                self._pre_func['func']()
            else:
                self._pre_func['func'](*args)

        route_info = ""
        for id in self._routes:
            node = next((n for n in context.nodes if n._id == id), None)
            if node:
                route_info += f"{node}: criteria: {self._routes.get(id)}\n"

        if len(self._routes) > 0:
            self._instructions += f"\nOnce you have answered the question, you will decide which node to route to based on the following criteria (node, criteria):\n" + route_info + "\nYou will then call the route tool to route to the next node, along with your rationale for routing to that node.\n"
        else:
            context.running = False

        if self._input:
            call_llm(self._input, instructions=self._instructions)
        else:
            call_llm(self._instructions)

        if self._post_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._post_func.get("args", [])
            if args is None:
                self._post_func['func']()
            else:
                self._post_func['func'](*args)