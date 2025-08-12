from src.minimal_agent_framework import Graph, Node, EventEmitter, tool, context
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

def change_my_name(name: str):
    context.name = name


def handler(x: str):
    print(f"{x}", end='', flush=True)

@tool
def get_the_magic_word() -> str:
    return "pineapple"

if __name__ == "__main__":
    # Example usage of Graph and Node
    
    events = EventEmitter()
    events.on("text", handler)

    context.name = "Randy"
    context.location = "Earth"
    context.events = events

    graph = Graph()

    node1 = Node()
    node2 = Node()
    node3 = Node()
    
    (node1
        .name("first").instructions("Speak like a pirate")
        .pre(sample_pre_function)
        .input("Hi. Use the magic word tool and tell me what the magic word is, then. Tell me if you know my name and location.")
        .routes({
            node2._id: "you do know my name and location",
            node3._id: "you do not know both my name and location",
            })
        .post(change_my_name, ["Ted"]))

    (node2
        .name("second")
        .input("Do you know my name?")
        .post(sample_post_function)
        .routes({
            node3._id: "this is the default criteria"
            })
        )

    node3 = (Node()
        .name("third")
        .input("Do you know my name now?")
        .post(sample_post_function)
        )
    
    logging.debug("Adding nodes to graph")
    graph.add_nodes([node1, node2, node3])
    
    graph.run(node1)