from src.minimal_agent_framework import Graph, Node, EventEmitter, tool, context, context_reset
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


def text_handler(x: str):
    print(f"{x}", end='', flush=True)

def tool_call_handler(x: str):
    print(f"\n🛠️  Tool Called: {x}\n")

def tool_result_handler(x: str):
    print(f"Tool result: {x}")

def error_handler(x: str):
    print(f"Error raised: {x}")

@tool
def get_the_magic_word() -> str:
    return "pineapple"

if __name__ == "__main__":
    # Example usage of Graph and Node
    
    events = EventEmitter()
    events.on("text", text_handler)
    events.on("tool_call", tool_call_handler)
    events.on("tool_result", tool_result_handler)
    events.on("error", error_handler)

    context.name = "Randy"
    context.location = "Earth"
    context.events = events

    graph = Graph()

    node1 = (Node()
        .name("first").instructions("Speak like a pirate")
        .pre(sample_pre_function)
        .input("Hi. Use the magic word tool and tell me what the magic word is, then. Tell me if you know my name and location.")
    )

    node2 = (Node()
        .name("second")
        .context({
            "dog_name": "Rocky"
        })
        .input("Tell me my dog's name. And, do you remember what the magic word is - if so, what was it?")
        .post(sample_post_function)
        )

    node3 = (Node()
        .name("third")
        .input("Do you know my name now?")
        .post(sample_post_function)
        )
    
    node1.routes({
        node2._id: "the magic word was pineapple",
        node3._id: "the magic word was grape",
        })
    
    node2.routes({
        node3._id: "default route",
        })
    
    logging.debug("Adding nodes to graph")
    graph.add_nodes([node1, node2, node3])
    
    graph.run(node1)