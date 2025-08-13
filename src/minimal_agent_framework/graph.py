from .node import Node
from .ctx import context
import logging
from .tool import tool
import os
from openai import OpenAI

@tool
def route(next_node_id: str, rationale: str):
    """
    Route to the next node:

    Arguments:

    next_node_id: the id of the node to route to
    rationale: the reason for choosing this node to route to
    """
    nodes = context.nodes
    next_node = next((n for n in nodes if n._id == next_node_id), None)
    if next_node:
        context.next_node = next_node
        return f"success: routing to {next_node._name} with rationale: {rationale}"
    else:
        return "failure"

class Graph():
    def __init__(self):
        if getattr(context, "nodes", None) is None:
            context.nodes = []
        if getattr(context, "client", None) is None:
            api_key = os.getenv("AZURE_API_KEY")
            base_url = os.getenv("AZURE_API_ENDPOINT")
            context.client = OpenAI(api_key=api_key, base_url=base_url, default_query={"api-version": "preview"})
            context.model = os.getenv("AZURE_MAIN_MODEL_DEPLOYMENT")
        context.response_id = None

    
    def add(self, node: Node) -> 'Graph':
        if not isinstance(node, Node):
            raise TypeError("Node must be an instance of Node.")
        context.nodes.append(node)
        return self

    def add_nodes(self, nodes: list[Node]) -> 'Graph':
        for node in nodes:
            if not isinstance(node, Node):
                raise TypeError("All items must be instances of Node.")
            context.nodes.append(node)
        return self
    
    def run(self, starting_node: Node):
        if not context.nodes:
            raise RuntimeError("Graph has no nodes to run.")
        if starting_node not in context.nodes:
            raise ValueError("Starting node must be part of the graph's nodes.")
        context.next_node = starting_node
        context.running = True

        while context.running == True:
            next_node = context.next_node
            if next_node:
                print(f"\n\n===== Starting node: {next_node._name}")
                logging.info(f"In Graph: Context next node: {next_node._name}")
                context.next_node.execute()
            else:
                logging.info("No next node to run.")
                context.running = False