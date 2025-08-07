class Node():
    def __init__(self):
        self._name = ""

    def name(self, name: str) -> 'Node':
        self._name: str = name
        self._routes: list[dict[str, str]] = []
        return self

    def routes(self, routes: list[dict[str, str]]) -> 'Node':
        self._routes = routes
        return self

    def execute(self) -> str:
        if self._routes:
            if len(self._routes) == 1:
                return list(self._routes[0].keys())[0]
        return ""