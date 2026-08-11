import datetime
import json
import os
import random
import re
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ollama  # pip install ollama

os.environ["TQDM_DISABLE"] = "1"

# --- Directory & Path Definitions ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if not os.path.exists(os.path.join(BEAR_ROOT, "MEMORY")):
    BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

if BEAR_ROOT not in sys.path:
    sys.path.insert(0, BEAR_ROOT)

# Dynamic Tool Loading & Explicit References
from TOOLS import tool_loader

# Retrieve tools dynamically or initialize explicit dicts/lists
if hasattr(tool_loader, "get_all_tools"):
    ALL_SCHEMAS, ALL_FUNCTIONS = tool_loader.get_all_tools()
elif hasattr(tool_loader, "load_tools"):
    ALL_SCHEMAS, ALL_FUNCTIONS = tool_loader.load_tools()
else:
    ALL_SCHEMAS = []
    ALL_FUNCTIONS = {}

MEMORY_DIR = os.path.join(BEAR_ROOT, "MEMORY")
MEMORY_LONG_DIR = os.path.join(MEMORY_DIR, "MEMORY-LONG")
SHORT_TERM_FILE = os.path.join(MEMORY_DIR, "chat_history.json")
AGENT_PROMPT_FILE = os.path.join(BEAR_ROOT, "Agent", "agentprompt.md")
MEMORY_PROMPT_FILE = os.path.join(MEMORY_DIR, "memoryprompt.md")
WEB_INDEX_FILE = os.path.join(BEAR_ROOT, "Web", "index.html")
EFFORT_CONFIG_FILE = os.path.join(BEAR_ROOT, "Web", "effort_config.json")

DEFAULT_MODEL = "qwen3:8b"
MAX_HISTORY_CHARS = 4800

os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(MEMORY_LONG_DIR, exist_ok=True)


# --- Helper File & Config Functions ---
def safe_read_text(path: str, default: str = "") -> str:
    """Safely load text content from a file."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return default


def load_effort_config() -> Dict[str, Any]:
    """Load effort presets with complete schema validation."""
    fallback = {
        "default_effort": "Low",
        "default_model": DEFAULT_MODEL,
        "efforts": {
            "Low": {
                "label": "Low",
                "instruction": "Keep the response concise and use minimal reasoning.",
            },
            "Medium": {
                "label": "Medium",
                "instruction": "Give a balanced response with enough explanation to be useful.",
            },
            "High": {
                "label": "High",
                "instruction": "Think step by step with more internal reasoning.",
            },
            "Max": {
                "label": "Max",
                "instruction": "Use maximum depth: break the task into subproblems and reason carefully before answering.",
            },
        },
    }

    try:
        with open(EFFORT_CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
        if not isinstance(config, dict):
            return fallback

        if "efforts" not in config and isinstance(config, dict):
            adapted_efforts = {}
            for k, v in config.items():
                instruction = v if isinstance(v, str) else v.get("instruction", "")
                adapted_efforts[k.title()] = {"label": k.title(), "instruction": instruction}
            fallback["efforts"].update(adapted_efforts)
            return fallback

        config.setdefault("default_effort", fallback["default_effort"])
        config.setdefault("default_model", fallback["default_model"])
        config.setdefault("efforts", fallback["efforts"])
        return config
    except (OSError, json.JSONDecodeError):
        return fallback


def normalize_effort(effort: Optional[str], config: Dict[str, Any]) -> str:
    options = config.get("efforts", {})
    default = config.get("default_effort", "Low")
    selected = str(effort or default).strip().title()
    return selected if selected in options else default


# --- Chat History & Memory Storage ---
def load_chat_history() -> List[Dict[str, Any]]:
    """Load rolling chat history trimmed to context budget."""
    try:
        with open(SHORT_TERM_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        messages = data.get("messages", []) if isinstance(data, dict) else data
        if not isinstance(messages, list):
            return []
    except (OSError, json.JSONDecodeError):
        return []

    total_chars = sum(len(item.get("content", "")) for item in messages if isinstance(item, dict))
    while total_chars > MAX_HISTORY_CHARS and len(messages) > 2:
        removed = messages.pop(0)
        total_chars -= len(removed.get("content", ""))

    return messages


def save_chat_history(messages: List[Dict[str, Any]]) -> None:
    """Filter and save active chat messages."""
    cleaned = [
        item
        for item in messages
        if isinstance(item, dict)
        and item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and not item.get("tool_calls")
    ]

    total_chars = sum(len(item["content"]) for item in cleaned)
    while total_chars > MAX_HISTORY_CHARS and len(cleaned) > 2:
        removed = cleaned.pop(0)
        total_chars -= len(removed["content"])

    with open(SHORT_TERM_FILE, "w", encoding="utf-8") as file:
        json.dump({"messages": cleaned}, file, indent=2, ensure_ascii=False)


def clear_short_term_memory() -> None:
    save_chat_history([])


def record_long_term_memory(user_prompt: str, answer: str) -> None:
    """Record an Obsidian-style Markdown node in long-term memory."""
    os.makedirs(MEMORY_LONG_DIR, exist_ok=True)
    ts = datetime.datetime.now()
    slug = ts.strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(MEMORY_LONG_DIR, f"memory-{slug}.md")

    content = f"""---
tags: [memory, ai-generated]
created: {ts.isoformat()}
---

> [!info] Conversation snapshot
> ==User==: {user_prompt}
> ==Bear==: {answer}

[[Bear]] [[Conversations]] [[MEMORY-LONG]]
#ai #memory #bear
"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as error:
        print(f"[Warning: Failed to save long-term memory - {error}]")


# --- Utilities & Guards ---
def compress_tokens(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def data_filter(query: str) -> bool:
    """Filter input against unsafe keywords/jailbreaks."""
    blocked = (
        "ignore previous instructions",
        "ignore all prior instructions",
        "bypass system",
        "drop table",
        "reveal hidden instructions",
        "rm -rf",
        "shutdown -h",
        "format c:",
    )
    text = str(query).lower()
    return not any(item in text for item in blocked)


# --- Ollama Setup & Tool Calls ---
def get_installed_ollama_models() -> List[str]:
    try:
        result = ollama.list()
        raw_models = (
            result.get("models", [])
            if isinstance(result, dict)
            else getattr(result, "models", [])
        )
        names = []
        for item in raw_models or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
            else:
                name = getattr(item, "model", None) or getattr(item, "name", None)
            if name and str(name) not in names:
                names.append(str(name))
        return names
    except Exception:
        return []


def resolve_model(model: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> str:
    if config is None:
        config = load_effort_config()

    requested = str(model or config.get("default_model", DEFAULT_MODEL)).strip()
    installed = get_installed_ollama_models()

    if not installed:
        return requested
    if requested in installed:
        return requested
    if "qwen3:8b" in installed:
        return "qwen3:8b"
    configured = config.get("default_model", DEFAULT_MODEL)
    return configured if configured in installed else installed[0]


def build_system_prompt(effort_instruction: str) -> str:
    agent_prompt = safe_read_text(
        AGENT_PROMPT_FILE,
        "You are Bear, a friendly local AI assistant. Talk naturally and do not use emojis.",
    )
    memory_prompt = safe_read_text(MEMORY_PROMPT_FILE)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt = (
        f"{agent_prompt}\n\n"
        f"--- MEMORY INSTRUCTIONS ---\n{memory_prompt}\n\n"
        f"Current Time: {current_time}"
    )

    if effort_instruction:
        prompt += f"\n\nEffort Instruction: {effort_instruction}"

    return prompt


def execute_tool_calls(
    response_message: Dict[str, Any],
    messages: List[Dict[str, Any]],
    all_functions: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Execute required tools and attach execution responses to message context."""
    messages.append(response_message)
    tools_used = []

    for call in response_message.get("tool_calls", []):
        function = call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", {})

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if not name or name not in all_functions:
            messages.append({
                "role": "tool",
                "name": name or "unknown",
                "content": "Error: tool was not found.",
            })
            continue

        tools_used.append(name)
        try:
            print(f"[System: Executing dynamic tool -> {name}]")
            result = all_functions[name](**arguments)
            content_str = (
                json.dumps(result, ensure_ascii=False)
                if isinstance(result, (dict, list))
                else compress_tokens(result)
            )
            messages.append({
                "role": "tool",
                "name": name,
                "content": content_str,
            })
        except Exception as error:
            messages.append({
                "role": "tool",
                "name": name,
                "content": f"Error running {name}: {error}",
            })

    return messages, tools_used


def launch_web_interface() -> None:
    index_path = Path(WEB_INDEX_FILE)
    if not index_path.exists():
        print(f"[Web UI not found: {index_path}]")
        return
    try:
        webbrowser.open(index_path.resolve().as_uri())
    except Exception as error:
        print(f"[Could not open Web UI: {error}]")


# --- Main Assistant Interface ---
def chat_with_bear_agent(
    user_prompt: str,
    effort: str = "Medium",
    model: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Primary chat pipeline handling context, safety, execution, and long-term memory."""
    user_prompt = str(user_prompt or "").strip()
    if not user_prompt:
        return "Please enter a message.", []

    if not data_filter(user_prompt):
        return "I can't process that request right now.", []

    config = load_effort_config()
    selected_effort = normalize_effort(effort, config)
    selected_model = resolve_model(model, config)

    effort_data = config.get("efforts", {}).get(selected_effort, {})
    instruction = effort_data.get("instruction", "Give a helpful response.")

    system_prompt = build_system_prompt(instruction)
    history = load_chat_history()

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_prompt},
    ]

    tools_used: List[str] = []

    try:
        response = ollama.chat(
            model=selected_model,
            messages=messages,
            tools=ALL_SCHEMAS or None,
        )

        resp_msg = response.get("message", {})
        if resp_msg.get("tool_calls"):
            messages, tools_used = execute_tool_calls(resp_msg, messages, ALL_FUNCTIONS)
            response = ollama.chat(model=selected_model, messages=messages)

        answer = str(response.get("message", {}).get("content", "")).strip()

    except Exception as error:
        return f"[System Error: could not reach model '{selected_model}' - {error}]", tools_used

    # Persist histories
    history.extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": answer},
    ])
    save_chat_history(history)
    record_long_term_memory(user_prompt, answer)

    return answer, tools_used


def trigger_startup_greeting() -> None:
    greetings = [
        "Bear is awake. What do you want to work on?",
        "Hey, I'm Bear. What's on your mind?",
        "Bear here. Ready when you are.",
        "Local Bear agent online. Fire away.",
    ]
    greeting = random.choice(greetings)
    print(f"Bear: {greeting}\n" + "-" * 40)


def main() -> None:
    launch_web_interface()

    print("========================================")
    print("BEAR PIPELINE ONLINE")
    print(f"Loaded {len(ALL_FUNCTIONS)} tools: {list(ALL_FUNCTIONS.keys()) if isinstance(ALL_FUNCTIONS, dict) else ALL_FUNCTIONS}")
    print("========================================\n")

    trigger_startup_greeting()

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue

            lower = user_input.lower()
            if lower in {"exit", "quit"}:
                print("Bear: Exiting...")
                break

            if lower == "clear":
                clear_short_term_memory()
                os.system("cls" if os.name == "nt" else "clear")
                print("\n[Memory Cleared - Ready for new conversation]\n")
                continue

            reply, tools = chat_with_bear_agent(user_input)

            print(f"\nBear: {reply}")
            if tools:
                print(f"[Tools Used: {', '.join(tools)}]")
            print("\n" + "-" * 40)

        except (KeyboardInterrupt, EOFError):
            print("\nBear: Bye.")
            break
        except Exception as error:
            print(f"\n[System Error: {error} - Chat is continuing...]\n")


if __name__ == "__main__":
    main()