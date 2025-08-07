from src.minimal_agent_framework import Graph, Node
import logging

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    # Example usage of Graph and Node
    graph = Graph()
    
    node1 = Node().name("Start").routes([{"NextNode": "default"}])
    node2 = Node().name("NextNode")
    
    graph.nodes.append(node1)
    graph.nodes.append(node2)
    
    graph.run(node1)