from src.minimal_agent_framework import Graph, Node, EventEmitter
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

for name in ("httpx", "httpcore"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.ERROR)

load_dotenv()

def sample_pre_function():
    logging.debug("Pre-function executed")

def sample_post_function():
    logging.debug("Post-function executed")

def handler(x: str):
    print(f"{x}", end='', flush=True)

if __name__ == "__main__":
    # Example usage of Graph and Node
    
    events = EventEmitter()
    events.on("text", handler)

    graph = Graph(events)
    
    node1 = (Node()
             .name("first")
             .input("Hi there!")
             .routes([{"second": "default"}])
             .pre(sample_pre_function)
             .post(sample_post_function))

    node2 = (Node()
             .name("second")
             .input("Do you have a name?")
             .routes([{"third": "default"}])
             .pre(sample_pre_function)
             .post(sample_post_function))

    node3 = (Node()
             .name("third")
             .input("Do you know what today's date is?")
             .post(sample_post_function)
             )
    
    graph.add(node1)
    graph.add_nodes([node2, node3])
    
    graph.run(node1)