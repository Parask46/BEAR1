import os
import json
import importlib
from typing import List, Dict, Any, Tuple


THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_tools() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Scan TOOLS/* for schema.json + tool_code.py, load schemas, and map
    function names to Python callables. Returns (schemas, function_map).
    """
    tool_schemas: List[Dict[str, Any]] = []
    function_map: Dict[str, Any] = {}

    for entry in os.listdir(THIS_DIR):
        tool_dir = os.path.join(THIS_DIR, entry)
        if not os.path.isdir(tool_dir):
            continue

        schema_path = os.path.join(tool_dir, "schema.json")
        code_path = os.path.join(tool_dir, "tool_code.py")
        if not (os.path.exists(schema_path) and os.path.exists(code_path)):
            continue

        # Load JSON schemas
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schemas = json.load(f)
            if isinstance(schemas, dict):
                schemas = [schemas]
        except Exception:
            continue

        # Import tool_code module
        module_name = f"TOOLS.{entry}.tool_code"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue

        # Register each function in schema with the module
        for s in schemas:
            fn_name = s.get("name")
            if not fn_name:
                continue
            if hasattr(mod, fn_name):
                tool_schemas.append(s)
                function_map[fn_name] = getattr(mod, fn_name)

    return tool_schemas, function_map