# Minimal Agent Framework

A tiny, streaming-first toolkit for:
- Registering function tools the model can call (via the Responses API)
- Orchestrating multi-step agent flows as a Graph of Nodes
- Injecting context and routing decisions between Nodes
- Emitting streaming text deltas to your UI through a simple EventEmitter

Status: early and minimal. Great for experiments and for embedding into your own editor/agent runtime.

---

## Features

- Function tools from plain Python functions using a decorator
- Tools auto-called by the model (Responses API) with arguments parsed from your type hints
- Streaming text output via a small EventEmitter
- Simple Graph/Node runtime with:
  - Pre/Post hooks (arbitrary Python)
  - Context injection into prompts
  - LLM-driven routing to next node with rationale
- Typed output using Pydantic models (optional)

---

## Requirements

- Python 3.10+
- Packages:
  - openai >= 1.60.0 (Responses API + streaming)
  - pydantic >= 2.0
  - python-dotenv
  - httpx (pulled in by openai)
  - pytest (optional, for tests)

Install:
```bash
pip install -U openai pydantic python-dotenv pytest
```

---

## Environment Setup

This project currently targets Azure OpenAI style configuration (you can adapt to OpenAI.com easily).

Set the following environment variables (e.g., in a `.env` file at repo root):

```env
AZURE_API_KEY=your_azure_openai_key
AZURE_API_ENDPOINT=https://your-azure-openai-resource.openai.azure.com
```

Notes:
- The model is hardcoded to "o4-mini" in src/minimal_agent_framework/utils.py. Change it there if needed.
- The code attaches default_query={"api-version":"preview"} to all requests.

To run modules that import `minimal_agent_framework`, add the src folder to PYTHONPATH:

```bash
export PYTHONPATH="$(pwd)/src"
```

---

## Project Layout

- src/minimal_agent_framework
  - __init__.py: public exports
  - tool.py: tool registry + @tool decorator
  - utils.py: OpenAI Responses API streaming wrapper + EventEmitter
  - node.py: Node definition + execution contract
  - graph.py: Graph orchestration and routing loop
- learn_api.py: simple tool + LLM call demo
- run_graph.py: Graph/Node example with pre/post hooks and routing
- tests/: basic tests (pytest)

---

## Quickstart

### 1) Register a Tool

Any plain function with type hints can be a tool. Decorate it with `@tool`.

```python
from minimal_agent_framework import tool

@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b
```

The framework builds a Pydantic schema from your signature and registers it with the OpenAI Responses API so the model can call it.

Constraints:
- No *args/**kwargs in tool functions
- Use type hints for arguments and a clear docstring for best results

### 2) Stream a Model Call (with optional typed output)

You can stream the model’s text deltas and parse the final output into a Pydantic model if you want structured fields.

```python
from dotenv import load_dotenv
from pydantic import BaseModel
from minimal_agent_framework import call_llm, EventEmitter

load_dotenv()

class Output(BaseModel):
    output_process_used: str
    output_text: str

def on_text(delta: str):
    print(delta, end="", flush=True)

events = EventEmitter()
events.on("text", on_text)

response = call_llm(
    input="Use the add_numbers tool to add 5 and 3, and also 10 and 20. "
          "Respond with the output text that will be seen by the user, "
          "and also return the process used to generate the output.",
    events=events,
    output=Output,           # optional; let the model return a JSON that parses to this schema
    # instructions="Anything extra you want to bias the model's behavior"
)

# When output=Output, response is an instance of Output
print("\n\nParsed response:", response)
```

What happens:
- Streaming deltas fire "text" events while the model is thinking
- If the model decides to call tools, the framework executes them and feeds their outputs back to the model
- Final response is parsed to your Pydantic model if you provided one

---

## Using the Graph and Node API

The Graph/Node orchestration lets you build multi-step flows where each Node:
- receives context (subset or all)
- runs optional pre/post Python functions
- prompts the model with an input + instructions
- asks the model to choose the next node (routing) with a rationale

### Core Classes

- Node
  - name(str)
  - context_keys(list[str]) — pick which keys to include in the prompt (["all"] to include everything)
  - input(str) — the main user/system content to discuss
  - instructions(str) — additional system-style guidance for this node
  - routes(list[dict[str, str]]) — [{"next_node_name": "criteria"}, ...]
  - pre(func, args=None) — arbitrary Python before the LLM call
  - post(func, args=None) — arbitrary Python after the LLM call
  - execute(events=None, full_context=None) -> str — runs the node and returns the name of the next node ("" if done)

- Graph
  - add(node)
  - add_nodes([node, ...])
  - run(starting_node, context: dict[str, str] = {}) — executes nodes until a node returns ""

### Example

```python
from src.minimal_agent_framework import Graph, Node, EventEmitter
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)

def pre_change_name(ctx: dict[str, str], name: str):
    ctx['name'] = name

def on_text(delta: str):
    print(delta, end="", flush=True)

events = EventEmitter()
events.on("text", on_text)

context = {"name": "Randy", "location": "Earth"}

graph = Graph(events)

node1 = (
    Node()
    .name("first")
    .context_keys(["location"])
    .input("Hi there! Do you know who I am and my location?")
    .instructions("Speak like a pirate.")
    .routes([
        {"second": "you do not know my location"},
        {"third": "you do not know my name"},
    ])
)

node2 = (
    Node()
    .name("second")
    .context_keys(["all"])
    .pre(pre_change_name, [context, "Ted"])
    .input("Do you know my name?")
    .routes([{"third": "this is the default criteria"}])
)

node3 = (
    Node()
    .name("third")
    .context_keys(["name"])
    .input("Do you know my name now?")
    # No routes -> terminal node; model should return next_node=""
)

graph.add_nodes([node1, node2, node3])

graph.run(node1, context)
```

How it works:
- Node1 gets only `"location"` from context, instructs the model to answer and then choose a next node based on provided criteria.
- If routed to "second", the pre-hook mutates the shared context to change the name to "Ted".
- Node3 is a terminal node (no routes) and ends the run by returning an empty next_node.

Notes:
- The Node’s instructions are automatically augmented with a formatted "Context:" section and routing instructions (if you configured routes).
- The model returns a structured JSON (parsed to a Pydantic Response inside the framework) including:
  - text_response_to_user
  - next_node
  - rationale
- Only next_node is returned from Node.execute; streaming text is emitted through the EventEmitter while the model responds.

---

## Streaming and EventEmitter

- Register a handler:
  ```python
  events = EventEmitter()
  events.on("text", lambda delta: print(delta, end=""))
  ```
- Pass events to either:
  - call_llm(..., events=events)
  - Graph(...events) and Node.execute will use call_llm under the hood

Currently only "text" deltas are emitted. Add more events in utils.py if you need richer signals.

---

## Tooling Details

- The @tool decorator registers your function with the ToolRegistry
- ToolRegistry creates a Pydantic model from your function signature and passes it through openai.pydantic_function_tool(...) to the Responses API
- During a streaming run:
  - Tool calls are surfaced as ResponseFunctionToolCall items
  - The framework executes your tool by name with parsed args, collects outputs
  - It then continues the same response via another call_llm pass, sending the function_call_output items back to the model
- Return types:
  - You can return any JSON-serializable result; non-dict results are stringified

Advanced:
- You can access ToolRegistry.get_tools() and ToolRegistry.reset() (useful in tests).

---

## Logging

The examples set:
- logging.basicConfig(level=logging.INFO)
- Quiet httpx/httpcore logs

Adjust as needed.

---

## Running the Examples

1) Terminal 1:
```bash
export PYTHONPATH="$(pwd)/src"
export $(cat .env | xargs)    # or rely on python-dotenv in the scripts
python learn_api.py
```

2) Terminal 2:
```bash
export PYTHONPATH="$(pwd)/src"
python run_graph.py
```

You should see streaming text output in the console as the model reasons and routes between nodes.

---

## Testing

```bash
pytest -q
```

Tip: If you’re writing tests that rely on tools or streaming, you can stub ToolRegistry or pass a fake EventEmitter to verify events.

---

## Troubleshooting

- ImportError: No module named 'minimal_agent_framework'
  - Make sure PYTHONPATH includes the src folder: export PYTHONPATH="$(pwd)/src"
- 401/403 from the API
  - Check AZURE_API_KEY and AZURE_API_ENDPOINT are correct and active
- Model not found
  - Update the model name in src/minimal_agent_framework/utils.py to a model available in your deployment
- Tool didn’t execute
  - Ensure your tool function is decorated with @tool and the process registers tools before call_llm is invoked
  - Keep function signatures simple (no *args/**kwargs); provide type annotations
- No next node to run
  - This is the expected end-of-graph message when a node returns an empty next_node

---

## Design Notes and Limitations

- Minimal prompt management: Node builds a single instruction string per call. If you need system vs user separation, extend utils.call_llm to pass richer input items.
- The Responses API text_format is used for typed outputs. Ensure your openai package is recent enough (>= 1.60) so output_parsed is populated correctly.
- The current API is synchronous with simple streaming; adapt to async if needed.
- Model selection is hardcoded; wire it to env vars if you want per-env configurability.

---

## License

Use at your own risk for now.