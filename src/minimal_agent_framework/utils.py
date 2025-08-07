from typing import Callable, get_type_hints
import inspect
from functools import wraps
from openai import OpenAI
from pydantic import BaseModel
from typing import Type, Optional

TOOL_REGISTRY: dict[str, Callable] = {}
TOOL_SCHEMAS: dict[str, dict] = {}

def tool(name: str):
    """Decorator to register tools for LLM use"""
    def decorator(func: Callable):
        # Generate OpenAI function schema
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)
        
        properties = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            if param_name == 'context':  # Skip context parameter
                continue
                
            param_type = type_hints.get(param_name, str)
            
            # Convert Python types to JSON Schema types
            if param_type == str:
                json_type = "string"
            elif param_type == int:
                json_type = "integer"
            elif param_type == float:
                json_type = "number"
            elif param_type == bool:
                json_type = "boolean"
            elif param_type == list:
                json_type = "array"
            elif param_type == dict:
                json_type = "object"
            else:
                json_type = "string"
            
            properties[param_name] = {
                "type": json_type,
                "description": f"Parameter {param_name}"
            }
            
            if param.default == param.empty:
                required.append(param_name)
        
        schema = {
            "name": name,
            "description": func.__doc__ or f"Tool: {name}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
        
        TOOL_REGISTRY[name] = func
        TOOL_SCHEMAS[name] = schema
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

class OpenAI_Client:
    def __init__(self, api_key: str, base_url: str, model: str = "o4-mini"):
        self.client = OpenAI(api_key=api_key, base_url=base_url, default_query={"api-version": "preview"})
        self.model = model

    def call_llm(self, user_prompt : str, instructions : str, output: Optional[Type[BaseModel]], restart_conversation: bool = False, tools: Optional[list[str]] = None):
        
        openai_tools = []
        if tools:
            for tool_name in tools:
                if tool_name in TOOL_SCHEMAS:
                    openai_tools.append({ 
                        "type": "function", 
                        "function": TOOL_SCHEMAS[tool_name]
                        })

        response = self.client.responses.create(
            model=self.model,
            input=user_prompt,
            instructions=instructions,
            tools=openai_tools,
            stream=True,
            temperature=0.1,
            truncation="auto",

        )

