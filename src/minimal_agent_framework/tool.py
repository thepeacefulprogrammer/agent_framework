import inspect
import json
import logging
from typing import Any, Callable, Dict, List, Optional, get_type_hints

import openai
from pydantic import BaseModel, create_model

logger = logging.getLogger(__name__)

class ToolRegistry:
    """Function-only tool registry for OpenAI Responses API."""
    _funcs: Dict[str, Callable[..., Any]] = {}
    _schemas: Dict[str, Any] = {}
    _order: List[str] = []  # preserves registration order

    @classmethod
    def register(
        cls,
        func: Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        replace: bool = False,
    ) -> Callable[..., Any]:
        tool_name = name or func.__name__
        if not replace and tool_name in cls._funcs:
            raise ValueError(f"Tool '{tool_name}' is already registered.")

        model = _build_model_from_func(func, tool_name, description)
        tool_schema = openai.pydantic_function_tool(model)

        cls._funcs[tool_name] = func
        cls._schemas[tool_name] = tool_schema
        if tool_name not in cls._order:
            cls._order.append(tool_name)

        logger.info(f"Registered tool: {tool_name}")
        return func  # keep original callable behavior

    @classmethod
    def get_tools(cls) -> List[Any]:
        """Return tool schemas for Responses API."""
        return [cls._schemas[name] for name in cls._order]

    @classmethod
    def call(cls, name: str, args: Any) -> Any:
        """Invoke a registered tool by name with dict or JSON-encoded args."""
        if name not in cls._funcs:
            raise KeyError(f"Tool '{name}' not found. Available: {list(cls._funcs.keys())}")

        fn = cls._funcs[name]

        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                logger.warning(f"Arguments for tool '{name}' not valid JSON; passing raw string")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise TypeError(f"Tool '{name}' expects dict args, got {type(args).__name__}")

        return fn(**args)

    @classmethod
    def reset(cls):
        """Clear all registered tools (useful in tests)."""
        cls._funcs.clear()
        cls._schemas.clear()
        cls._order.clear()


def tool(
    func: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    replace: bool = False
):
    """
    Decorator to turn a function into a registered tool.

    @tool
    def my_tool(a: int) -> str: ...

    @tool(name="custom", description="...", replace=True)
    def other(...): ...
    """
    def _decorator(f: Callable[..., Any]):
        return ToolRegistry.register(f, name=name, description=description, replace=replace)

    return _decorator if func is None else _decorator(func)


def _build_model_from_func(func: Callable[..., Any], model_name: str, description: Optional[str]) -> type[BaseModel]:
    """
    Build a Pydantic model from the function signature.
    - Types come from annotations (supports Annotated[...] with Field(...)).
    - Defaults come from function defaults.
    - Zero-arg functions are supported.
    """
    sig = inspect.signature(func)
    # include_extras=True preserves Annotated metadata (e.g., Field)
    hints = get_type_hints(func, include_extras=True)  # type: ignore[arg-type]

    # Dict[str, Any] helps Pylance not over-constrain kwargs to create_model
    fields: Dict[str, Any] = {}
    for param in sig.parameters.values():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(f"@tool does not support *args/**kwargs for '{model_name}'.")

        ann = hints.get(param.name, Any)
        default = param.default if param.default is not inspect._empty else ...
        fields[param.name] = (ann, default)

    # Avoid passing __doc__ to create_model; set it after. __module__ is safe.
    model = create_model(
        model_name,
        __module__=func.__module__,
        **fields,
    )
    model.__doc__ = description or (func.__doc__ or "")

    return model
