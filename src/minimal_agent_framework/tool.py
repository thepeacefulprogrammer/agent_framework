import openai
import json
import logging

from pydantic import BaseModel
from pydantic import BaseModel, create_model
from typing import Callable, Any, ClassVar

class Tool:
    # Class-level registry
    registry: ClassVar[dict[str, Callable[..., Any]]] = {}
    tools: ClassVar[list] = []
    tool_classes: ClassVar[dict[str, type['Tool']]] = {}
    
    def __init_subclass__(cls, *args, **kwargs):
        """Called when a class inherits from Tool"""
        super().__init_subclass__(*args, **kwargs)
        
        # Only register if the class has a run method (skip abstract base)
        if hasattr(cls, 'run') and callable(getattr(cls, 'run')):
            name = cls.__name__
            Tool.registry[name] = cls.run
            
            if hasattr(cls, '__annotations__'):
                fields = {}
                for field_name, field_type in cls.__annotations__.items():
                    if not (hasattr(field_type, '__origin__') and field_type.__origin__ is ClassVar):
                        fields[field_name] = (field_type, ...)
            
                if fields:
                    model_class = create_model(name, __doc__=cls.__doc__, **fields)
                    tool_schema = openai.pydantic_function_tool(model_class)
                else:
                    tool_schema = openai.pydantic_function_tool(BaseModel)
            else:
                tool_schema = openai.pydantic_function_tool(BaseModel)
            
            Tool.tools.append(tool_schema)
            logging.info(f"Registered tool: {name} with schema: {tool_schema}")
    
    @classmethod
    def call_function(cls, name: str, args) -> str:
        """Call a registered function"""
        print(f"Calling function: {name} with args: {args}")
        if name in Tool.registry:
            func = Tool.registry[name]
            try:
                if isinstance(args, str):
                    args = json.loads(args)
                result = func(**args)
                return result if result is not None else "success"
            except Exception as e:
                logging.error(f"Error executing function {name}: {e}")
                return str(e)
        else:
            logging.error(f"Function {name} not found in registry.")
            logging.error(f"Available functions: {list(Tool.registry.keys())}")
            return f"error Function {name} not found."
    
    @classmethod
    def get_all_tools(cls) -> list:
        """Get all registered tools for OpenAI"""
        return Tool.tools
    
    @classmethod
    def run(cls, *args, **kwargs) -> str:
        """Default run method to be overridden by subclasses"""
        raise NotImplementedError("Subclasses must implement the run method.")

def tool(cls):
    """Decorator to convert a class into a Tool"""
    # Create a new class that inherits from both Tool and the decorated class
    tool_class = type(
        cls.__name__,
        (Tool,),  # Inherit from Tool
        {
            '__doc__': cls.__doc__,
            '__annotations__': cls.__annotations__ if hasattr(cls, '__annotations__') else {},
            'run': cls.run if hasattr(cls, 'run') else Tool.run,
            # Copy any other class attributes
            **{k: v for k, v in cls.__dict__.items() 
               if not k.startswith('__') and k != 'run'}
        }
    )
    
    return tool_class