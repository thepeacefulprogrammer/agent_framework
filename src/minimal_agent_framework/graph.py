from .node import Node
import logging

class Graph():
    def __init__(self):
        self.nodes: list[Node] = []
        self.starting_node : Node | None = None
    
    def run(self, starting_node: Node):
        if not self.nodes:
            raise RuntimeError("Graph has no nodes to run.")
        if starting_node not in self.nodes:
            raise ValueError("Starting node must be part of the graph's nodes.")
        node_lookup = {node._name: node for node in self.nodes}
        self.starting_node = starting_node
        next_node = self.starting_node.execute()
        while len(next_node) > 0:
            if next_node not in node_lookup:
                raise ValueError(f"Node {next_node} not found in graph nodes.")
            for node in self.nodes:
                if node._name == next_node:
                    next_node = node.execute()
                    break
            next_node = ""
        else:
            print("No next node to run.")