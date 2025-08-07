from .node import Node

class Graph():
    def __init__(self):
        self.nodes: list[Node] = []
        self.starting_node : Node | None = None
    
    def run(self):
        if not self.nodes:
            raise RuntimeError("Graph has no nodes to run.")
        pass
