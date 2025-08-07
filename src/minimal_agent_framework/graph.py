from .node import Node

class Graph():
    def __init__(self):
        self.nodes: list[Node] = []
        self.starting_node : Node | None = None
    
    def run(self, starting_node: Node):
        if not self.nodes:
            raise RuntimeError("Graph has no nodes to run.")
        if starting_node not in self.nodes:
            raise ValueError("Starting node must be part of the graph's nodes.")
        self.starting_node = starting_node
        self.starting_node.execute()
