from .node import Node
from .utils import EventEmitter
import logging

class Graph():
    def __init__(self, events : EventEmitter | None = None):
        self.nodes: list[Node] = []
        self.events = events
    
    def add(self, node: Node) -> 'Graph':
        if not isinstance(node, Node):
            raise TypeError("Node must be an instance of Node.")
        self.nodes.append(node)
        return self

    def add_nodes(self, nodes: list[Node]) -> 'Graph':
        for node in nodes:
            if not isinstance(node, Node):
                raise TypeError("All items must be instances of Node.")
            self.nodes.append(node)
        return self
    
    def run(self, starting_node: Node, context: dict[str, str] = {}):
        if not self.nodes:
            raise RuntimeError("Graph has no nodes to run.")
        if starting_node not in self.nodes:
            raise ValueError("Starting node must be part of the graph's nodes.")
        node_lookup = {node._name: node for node in self.nodes}
        next_node = starting_node.execute(self.events, full_context=context)
        while len(next_node) > 0:
            if next_node not in node_lookup:
                raise ValueError(f"Node {next_node} not found in graph nodes.")
            for node in self.nodes:
                if node._name == next_node:
                    next_node = node.execute(self.events, full_context=context)
                    break
        else:
            print("No next node to run.")