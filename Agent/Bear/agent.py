import datetime
import json
import os
import random
import re
import sys
import webbrowser
from pathlib import Path

os.environ["TQDM_DISABLE"] = "1"

import ollama

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if BEAR_ROOT not in sys.path:
    sys.path.insert(0, BEAR_ROOT)

from TOOLS import tool_loader

ALL_SCHEMAS, ALL_FUNCTIONS = tool_loader.get_all_tools()

MEMORY_DIR = os.path.join(BEAR_ROOT, "MEMORY")
SHORT_TERM_FILE = os.path.join(MEMORY_DIR, "chat_history.json")
AGENT_PROMPT_FILE = os.path.join(BEAR_ROOT, "Agent", "agentprompt.md")
MEMORY_PROMPT_FILE = os.path.join(MEMORY_DIR, "memoryprompt.md")
WEB_INDEX_FILE = os.path.join(BEAR_ROOT, "Web", "index.html")
EFFORT_CONFIG_FILE = os.path.join(BEAR_ROOT, "Web", "effort_config.json")

DEFAULT_MODEL = "qwen3:8b"
MAX_HISTORY_CHARS = 4800

os.makedirs(MEMORY_DIR, exist_ok=True)


def load_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return default


def load_chat_history():
    try:
        with open(SHORT_TERM_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        messages = data.get("messages", []) if isinstance(data, dict) else []
        return messages if isinstance(messages, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_chat_history(messages):
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
        json.dump(
            {"messages": cleaned},
            file,
            indent=2,
            ensure_ascii=False,
        )


def clear_short_term_memory():
    save_chat_history([])


def compress_tokens(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def content_classifier(output):
    return str(output or "").strip()


def data_filter(query):
    blocked = (
        "ignore previous instructions",
        "bypass system",
        "drop table",
    )
    text = str(query).lower()
    return not any(item in text for item in blocked)


def load_effort_config():
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
                "instruction": "Think carefully, check important details, and give a thorough response.",
            },
            "Max": {
                "label": "Max",
                "instruction": "Use detailed, carefully checked reasoning and provide a thorough response.",
            },
        },
    }

    try:
        with open(EFFORT_CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)
        if not isinstance(config, dict):
            return fallback
        config.setdefault("default_effort", fallback["default_effort"])
        config.setdefault("default_model", fallback["default_model"])
        config.setdefault("efforts", fallback["efforts"])
        return config
    except (OSError, json.JSONDecodeError):
        return fallback


def normalize_effort(effort, config):
    options = config.get("efforts", {})
    default = config.get("default_effort", "Low")
    selected = str(effort or default).strip().title()
    return selected if selected in options else default


def get_installed_ollama_models():
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


def resolve_model(model, config):
    requested = str(model or config.get("default_model", DEFAULT_MODEL)).strip()
    installed = get_installed_ollama_models()
    if not installed:
        return requested
    if requested in installed:
        return requested
    configured = config.get("default_model", DEFAULT_MODEL)
    return configured if configured in installed else installed[0]


def launch_web_interface():
    index_path = Path(WEB_INDEX_FILE)
    if not index_path.exists():
        print(f"[Web UI not found: {index_path}]")
        return
    try:
        webbrowser.open(index_path.resolve().as_uri())
    except Exception as error:
        print(f"[Could not open Web/index.html: {error}]")


def execute_tool_calls(response_message, messages):
    messages.append(response_message)

    for call in response_message.get("tool_calls", []):
        function = call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", {})

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if name not in ALL_FUNCTIONS:
            messages.append({
                "role": "tool",
                "name": name or "unknown",
                "content": "Error: tool was not found.",
            })
            continue

        try:
            print(f"[System: Executing dynamic tool -> {name}]")
            result = ALL_FUNCTIONS[name](**arguments)
            messages.append({
                "role": "tool",
                "name": name,
                "content": compress_tokens(result),
            })
        except Exception as error:
            messages.append({
                "role": "tool",
                "name": name,
                "content": f"Error running {name}: {error}",
            })

    return messages


def trigger_startup_greeting():
    if random.random() > 0.5:
        return

    current_time = datetime.datetime.now().strftime(
        "%A, %B %d, %Y at %I:%M:%S %p"
    )
    agent_prompt = load_file(
        AGENT_PROMPT_FILE,
        "You are Bear, a friendly local AI assistant. Talk naturally and do not use emojis.",
    )
    messages = [
        {
            "role": "system",
            "content": f"{agent_prompt}\n\nCurrent Time: {current_time}",
        },
        {
            "role": "user",
            "content": "[Cmd: Met user. Start naturally with a short greeting.]",
        },
    ]

    try:
        config = load_effort_config()
        model = resolve_model(config.get("default_model"), config)
        response = ollama.chat(model=model, messages=messages)
        greeting = response["message"]["content"]
    except Exception as error:
        print(f"[Startup greeting failed: {error}]")
        return

    history = load_chat_history()
    history.append({"role": "assistant", "content": greeting})
    save_chat_history(history)
    print(f"Bear: {greeting}\n")
    print("-" * 40)


def chat_with_bear_agent(user_prompt, effort=None, model=None):
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
    prompt = (
        f"[Response effort: {selected_effort}]\n"
        f"{instruction}\n\n"
        f"{user_prompt}"
    )

    agent_prompt = load_file(
        AGENT_PROMPT_FILE,
        "You are Bear, a friendly local AI assistant. Talk naturally and do not use emojis.",
    )
    memory_prompt = load_file(MEMORY_PROMPT_FILE)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        f"{agent_prompt}\n\n"
        f"--- MEMORY INSTRUCTIONS ---\n{memory_prompt}\n\n"
        f"Current Time: {current_time}"
    )

    history = load_chat_history()
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": prompt},
    ]

    tools_used = []
    try:
        response = ollama.chat(
            model=selected_model,
            messages=messages,
            tools=ALL_SCHEMAS or None,
        )

        if response.get("message", {}).get("tool_calls"):
            # Track which tools were utilized
            for call in response["message"]["tool_calls"]:
                tool_name = call.get("function", {}).get("name", "Unknown")
                tools_used.append(tool_name)

            messages = execute_tool_calls(response["message"], messages)
            response = ollama.chat(model=selected_model, messages=messages)

        answer = content_classifier(
            response.get("message", {}).get("content", "")
        )
    except Exception as error:
        return f"[System Error: could not reach model '{selected_model}' - {error}]", tools_used

    history.extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": answer},
    ])
    save_chat_history(history)
    return answer, tools_used


def main():
    launch_web_interface()

    print("========================================")
    print("BEAR PIPELINE ONLINE")
    print(f"Loaded {len(ALL_FUNCTIONS)} tools: {list(ALL_FUNCTIONS)}")
    print("========================================\n")

    trigger_startup_greeting()

    try:
        while True:
            try:
                user_input = input("You: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in {"exit", "quit"}:
                    print("Shutting down...")
                    break
                if user_input.lower() == "clear":
                    clear_short_term_memory()
                    print("\n[Memory Cleared - Ready for new conversation]\n")
                    continue

                reply, tools = chat_with_bear_agent(user_input)

                print(f"\nBear: {reply}")
                if tools:
                    print(f"[Tools Used: {', '.join(tools)}]")
                print("\n" + "-" * 40)
            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as error:
                print(f"\n[System Error: {error} - Chat is continuing...]\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()