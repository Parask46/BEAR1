import os
import json
import importlib
import sys

# Ensure C:\BEAR is in the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if BEAR_ROOT not in sys.path:
    sys.path.append(BEAR_ROOT)

def get_all_tools():
    schemas = []
    available_functions = {}
    
    # Loop through every item in the TOOLS directory
    for item in os.listdir(SCRIPT_DIR):
        item_path = os.path.join(SCRIPT_DIR, item)
        
        # If it's a folder (like 'memory', 'web_search') and not a hidden folder
        if os.path.isdir(item_path) and not item.startswith('__'):
            schema_path = os.path.join(item_path, 'schema.json')
            code_module_name = f"TOOLS.{item}.tool_code"
            
            if os.path.exists(schema_path):
                try:
                    # 1. Load the "triggers" and prompts (Schema)
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        tool_schemas = json.load(f)
                        if not isinstance(tool_schemas, list):
                            tool_schemas = [tool_schemas]
                        schemas.extend(tool_schemas)
                    
                    # 2. Load the Python code dynamically
                    module = importlib.import_module(code_module_name)
                    
                    # 3. Map the schema names to the actual python functions
                    for schema in tool_schemas:
                        func_name = schema['function']['name']
                        if hasattr(module, func_name):
                            available_functions[func_name] = getattr(module, func_name)
                            
                except Exception as e:
                    print(f"[Warning: Failed to load tool '{item}': {e}]")
                    
    return schemas, available_functions