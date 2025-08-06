from .node import Node

class Graph():
    def __init__(self):
        self.nodes: list[Node] = []
        self.starting_node = None
