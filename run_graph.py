from src.minimal_agent_framework import Graph, Node
import logging

logging.basicConfig(level=logging.DEBUG)

def sample_pre_function():
    logging.debug("Pre-function executed")

def sample_post_function():
    logging.debug("Post-function executed")

if __name__ == "__main__":
    # Example usage of Graph and Node
    graph = Graph()
    
    node1 = (Node()
             .name("Start")
             .routes([{"NextNode": "default"}])
             .pre(sample_pre_function)
             .post(sample_post_function))

    node2 = (Node()
             .name("NextNode")
             .post(sample_post_function)
             )
    
    graph.nodes.append(node1)
    graph.nodes.append(node2)
    
    graph.run(node1)