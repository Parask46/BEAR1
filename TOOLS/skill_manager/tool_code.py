import os
import sys
import json
import importlib.util

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
SKILLS_DIR = os.path.join(BEAR_ROOT, 'SKILLS')

def execute_custom_skill(skill_name: str, function_name: str, kwargs_json: str = "{}") -> str:
    """Loads and runs custom user skills on demand."""
    filepath = os.path.join(SKILLS_DIR, f"{skill_name}.py")
    if not os.path.exists(filepath):
        return f"Skill '{skill_name}' not found at {filepath}."

    try:
        kwargs = json.loads(kwargs_json) if kwargs_json else {}
        spec = importlib.util.spec_from_file_location(skill_name, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, function_name):
            return f"Function '{function_name}' not found in skill '{skill_name}'."

        func = getattr(module, function_name)
        result = func(**kwargs)
        return str(result)
    except Exception as e:
        return f"Custom Skill Error ({skill_name}.{function_name}): {str(e)}"