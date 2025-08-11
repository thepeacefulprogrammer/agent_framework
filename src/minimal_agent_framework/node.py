import logging
from typing import Optional, Callable, Any, get_type_hints
from .utils import EventEmitter, call_llm
import inspect

class Node():
    def __init__(self):
        self._name = ""
        self._routes: list[dict[str, str]] = []
        self._pre_func: dict[str, Any] = {}
        self._post_func: Optional[Callable[..., Any]] = None
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

    def post(self, func: Callable) -> 'Node':
        self._post_func = func
        return self
    
    def execute(self, events : EventEmitter | None = None, full_context: dict[str, str] | None = None) -> str:
        logging.debug(f"Executing node: {self._name}")
        
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

            if not self._instructions:
                self._instructions = ""
            self._instructions += "\nContext: key:value\n" + " ".join(f"{k}: {v}\n" for k, v in self._context.items())

        if events:
            if self._input and self._instructions:
                call_llm(self._input, instructions=self._instructions, events=events)
            elif self._input:
                call_llm(self._input, events=events)

        if self._post_func:
            logging.debug(f"Running post-function for node: {self._name}")
            self._post_func()

        if self._routes:
            if len(self._routes) == 1:
                return list(self._routes[0].keys())[0]
        return ""