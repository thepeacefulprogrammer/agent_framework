import logging
from typing import Optional, Callable, Any
from pydantic import BaseModel
from .utils import EventEmitter, call_llm

class Response(BaseModel):
    """Response model for the node execution.
    
    Attributes:
        text_response_to_user: The response text to be sent to the user.
        next_node: The name of the next node to route to.
        rationale: The reasoning behind the choice of the next node.
    """
    text_response_to_user: str
    next_node: str
    rationale: str


class Node():
    def __init__(self):
        self._name = ""
        self._routes: list[dict[str, str]] = []
        self._pre_func: dict[str, Any] = {}
        self._post_func: dict[str, Any] = {}
        self._instructions: Optional[str] = None
        self._input: Optional[str] = None
        self._context_keys: list[str] = []

    def context_keys(self, keys: list[str]) -> 'Node':
        """Set a context variable for the node."""
        self._context_keys = keys
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

    def routes(self, routes: list[dict[str, str]]) -> 'Node':
        self._routes = routes
        return self
    
    def pre(self, func: Callable, args: list | None = None) -> 'Node':
        self._pre_func = {"func": func, "args": args}
        return self

    def post(self, func: Callable, args: list | None = None) -> 'Node':
        self._post_func = {"func": func, "args": args}
        return self
    
    def execute(self, events : EventEmitter | None = None, full_context: dict[str, str] | None = None) -> str:
        logging.debug(f"Executing node: {self._name}")

        if not self._instructions:
                self._instructions = ""
        
        if self._pre_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._pre_func.get("args", [])
            if args is None:
                self._pre_func['func']()
            else:
                self._pre_func['func'](*args)

        if len(self._context_keys) > 0 and full_context:
            if self._context_keys[0] == "all":
                self._context = full_context
            else:
                self._context = {key: full_context[key] for key in self._context_keys if key in full_context}
            logging.debug(f"Context for node {self._name}: {self._context}")

            self._instructions += "\nContext: (key: value)\n" + " ".join(f"{k}: {v}\n" for k, v in self._context.items())

        if len(self._routes) > 0:
            self._instructions += f"\nOnce you have answered the question, you will decide which node to route to based on the following criteria (name, criteria):\n" + "".join(f"{list(route.keys())[0]}: criteria = {list(route.values())[0]}\n" for route in self._routes) + "\nProvide the rationale for your choice in the response.\n"
        else:
            self._instructions += "\nThere is no next node, so return an empty string"

        response = ""
        if events:
            if self._input:
                response = call_llm(self._input, instructions=self._instructions, events=events, output=Response)
            else:
                response = call_llm(self._instructions, events=events, output=Response)

        if self._post_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            args = self._post_func.get("args", [])
            if args is None:
                self._post_func['func']()
            else:
                self._post_func['func'](*args)

        r = Response.model_validate(response)
        return r.next_node