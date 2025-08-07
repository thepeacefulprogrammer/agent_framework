import logging
from typing import Optional, Callable

class Node():
    def __init__(self):
        self._name = ""

    def name(self, name: str) -> 'Node':
        self._name: str = name
        self._routes: list[dict[str, str]] = []
        self._pre_func: Optional[Callable] = None
        self._post_func: Optional[Callable] = None
        return self

    def routes(self, routes: list[dict[str, str]]) -> 'Node':
        self._routes = routes
        return self
    
    def pre(self, func: Callable) -> 'Node':
        self._pre_func = func
        return self
    
    def post(self, func: Callable) -> 'Node':
        self._post_func = func
        return self

    def execute(self) -> str:
        logging.debug(f"Executing node: {self._name}")
        
        if self._pre_func:
            logging.debug(f"Running pre-function for node: {self._name}")
            self._pre_func()

        if self._post_func:
            logging.debug(f"Running post-function for node: {self._name}")
            self._post_func()

        if self._routes:
            if len(self._routes) == 1:
                return list(self._routes[0].keys())[0]
        return ""