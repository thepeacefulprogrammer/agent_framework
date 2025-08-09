
from dotenv import load_dotenv
from minimal_agent_framework import tool, call_llm, EventEmitter
from pydantic import BaseModel

import logging
logging.basicConfig(level=logging.INFO)

for name in ("httpx", "httpcore"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.ERROR)

load_dotenv()

@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

class OutputTest(BaseModel):
    """Test output model."""
    output_process_used: str
    output_text: str

def handler(x: str):
    print(f"{x}", end='', flush=True)


if __name__ == "__main__":

    events = EventEmitter()
    events.on("text", handler)

    response = call_llm(input="use the add_numbers tool to add 5 and 3, and then use it again to add 10 and 20. Respond with the output text that will be seen by the user, and also return the process used to generate the output.", events=events)    

