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
             .context_keys(["name", "location"])
             .input("Hi there! Do you know who I am and my location?")
             .instructions("Speak like a prirate")
             .routes([{"second": "default"}])
             .pre(sample_pre_function)
             .post(sample_post_function))

    node2 = (Node()
             .name("second")
             .context_keys(["all"])
             .input("Do you know my name?")
             .routes([{"third": "default"}])
             .pre(sample_pre_function)
             .post(sample_post_function))

    node3 = (Node()
             .name("third")
             .input("Do you know what today's date is?")
             .post(sample_post_function)
             )
    
    graph.add_nodes([node1, node2, node3])
    context = {
        "name": "Randy",
        "location": "Earth"
    }
    graph.run(node1, context)