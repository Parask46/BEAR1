import os
import sys
import datetime
import json
import random
import time
import sqlite3
import re
import webbrowser
from pathlib import Path

os.environ["TQDM_DISABLE"] = "1"

import ollama

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if BEAR_ROOT not in sys.path:
    sys.path.append(BEAR_ROOT)

from TOOLS import tool_loader

ALL_SCHEMAS, ALL_FUNCTIONS = tool_loader.get_all_tools()

MEMORY_DIR = os.path.join(BEAR_ROOT, "MEMORY")
SHORT_TERM_FILE = os.path.join(MEMORY_DIR, "chat_history.json")
AGENT_PROMPT_FILE = os.path.join(BEAR_ROOT, "Agent", "agentprompt.md")
MEMORY_PROMPT_FILE = os.path.join(MEMORY_DIR, "memoryprompt.md")
WEB_INDEX_FILE = os.path.join(BEAR_ROOT, "Web", "index.html")

LLM_MODEL = "qwen3:8b"
MAX_HISTORY_CHARS = 4800
LLM_CACHE_MAX_ENTRIES = 500

os.makedirs(MEMORY_DIR, exist_ok=True)


class LLMCache:
    """SQLite response cache with a size limit."""

    def __init__(self, db_path=None, max_entries=LLM_CACHE_MAX_ENTRIES):
        self.db_path = db_path or os.path.join(MEMORY_DIR, "llm_cache.db")
        self.max_entries = max_entries
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                query TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                last_used REAL NOT NULL DEFAULT 0
            )"""
        )

        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(cache)").fetchall()
        }

        if "last_used" not in columns:
            self.conn.execute(
                "ALTER TABLE cache ADD COLUMN last_used REAL NOT NULL DEFAULT 0"
            )

        self.conn.commit()

    @staticmethod
    def _normalize(query):
        return query.strip().lower()

    def get(self, query):
        key = self._normalize(query)
        row = self.conn.execute(
            "SELECT response FROM cache WHERE query = ?", (key,)
        ).fetchone()

        if row is None:
            return None

        self.conn.execute(
            "UPDATE cache SET last_used = ? WHERE query = ?",
            (time.time(), key),
        )
        self.conn.commit()
        return row[0]

    def set(self, query, response):
        key = self._normalize(query)
        self.conn.execute(
            """INSERT OR REPLACE INTO cache
               (query, response, last_used) VALUES (?, ?, ?)""",
            (key, response, time.time()),
        )

        overflow = self.conn.execute(
            "SELECT COUNT(*) FROM cache"
        ).fetchone()[0] - self.max_entries

        if overflow > 0:
            self.conn.execute(
                """DELETE FROM cache WHERE query IN
                   (SELECT query FROM cache ORDER BY last_used ASC LIMIT ?)""",
                (overflow,),
            )

        self.conn.commit()

    def close(self):
        self.conn.close()


llm_cache = LLMCache()


def load_file(filepath, default_text=""):
    if not os.path.exists(filepath):
        return default_text

    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return default_text


def clear_short_term_memory():
    with open(SHORT_TERM_FILE, "w", encoding="utf-8") as file:
        json.dump({"messages": []}, file, indent=2)


def load_chat_history():
    if not os.path.exists(SHORT_TERM_FILE):
        return []

    try:
        with open(SHORT_TERM_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data.get("messages", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_chat_history(messages):
    clean_messages = [
        message
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and not message.get("tool_calls")
        and isinstance(message.get("content"), str)
    ]

    total_chars = sum(len(message["content"]) for message in clean_messages)

    while total_chars > MAX_HISTORY_CHARS and len(clean_messages) > 2:
        removed = clean_messages.pop(0)
        total_chars -= len(removed["content"])

    with open(SHORT_TERM_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {"messages": clean_messages},
            file,
            indent=2,
            ensure_ascii=False,
        )


def compress_tokens(text):
    return re.sub(r"\s+", " ", str(text)).strip() if text else ""


def data_filter(query):
    blocked_keywords = (
        "ignore previous instructions",
        "bypass system",
        "drop table",
    )
    query_lower = query.lower()
    return not any(keyword in query_lower for keyword in blocked_keywords)


def content_classifier(output):
    return output.strip()


def launch_web_interface():
    """Open Web/index.html in the default browser when Bear starts."""
    index_path = Path(WEB_INDEX_FILE)

    if not index_path.exists():
        print(f"[Web UI not found: {index_path}]")
        return

    try:
        webbrowser.open(index_path.resolve().as_uri())
    except Exception as error:
        print(f"[Could not open Web/index.html: {error}]")


def execute_tool_calls(response_message, messages):
    """Run each tool independently so one failed tool does not end the chat."""
    messages.append(response_message)

    for tool_call in response_message.get("tool_calls", []):
        function = tool_call.get("function", {})
        function_name = function.get("name")
        arguments = function.get("arguments", {})

        if function_name not in ALL_FUNCTIONS:
            messages.append(
                {
                    "role": "tool",
                    "name": function_name or "unknown",
                    "content": "Error: tool was not found.",
                }
            )
            continue

        try:
            print(f"[System: Executing dynamic tool -> {function_name}]")
            result = ALL_FUNCTIONS[function_name](**arguments)
            messages.append(
                {
                    "role": "tool",
                    "name": function_name,
                    "content": compress_tokens(result),
                }
            )
        except Exception as error:
            messages.append(
                {
                    "role": "tool",
                    "name": function_name,
                    "content": f"Error running {function_name}: {error}",
                }
            )

    return messages


def trigger_startup_greeting():
    if random.random() > 0.5:
        return

    print("\n[System: Bear is initiating conversation...]\n")
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
        response = ollama.chat(model=LLM_MODEL, messages=messages)
        greeting = response["message"]["content"]
    except Exception as error:
        print(f"[Startup greeting failed: {error}]")
        return

    history = load_chat_history()
    history.append({"role": "assistant", "content": greeting})
    save_chat_history(history)
    print(f"Bear: {greeting}\n")
    print("-" * 40)


def chat_with_bear_agent(user_prompt):
    if not data_filter(user_prompt):
        return "I can't process that request right now."

    cached_response = llm_cache.get(user_prompt)
    if cached_response:
        history = load_chat_history()
        history.extend(
            [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": cached_response},
            ]
        )
        save_chat_history(history)
        return cached_response

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agent_prompt = load_file(
        AGENT_PROMPT_FILE,
        "You are Bear, a friendly local AI assistant. Talk naturally and do not use emojis.",
    )
    memory_prompt = load_file(MEMORY_PROMPT_FILE)

    system_instruction = (
        f"{agent_prompt}\n\n"
        f"--- MEMORY INSTRUCTIONS ---\n{memory_prompt}\n\n"
        f"Current Time: {current_time}"
    )

    history = load_chat_history()
    messages = [{"role": "system", "content": system_instruction}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = ollama.chat(
            model=LLM_MODEL,
            messages=messages,
            tools=ALL_SCHEMAS or None,
        )
    except Exception as error:
        return f"[System Error: could not reach the model - {error}]"

    if response.get("message", {}).get("tool_calls"):
        messages = execute_tool_calls(response["message"], messages)

        try:
            response = ollama.chat(model=LLM_MODEL, messages=messages)
        except Exception as error:
            return f"[System Error: model unreachable after tool execution - {error}]"

    assistant_reply = content_classifier(
        response["message"].get("content", "")
    )
    llm_cache.set(user_prompt, assistant_reply)

    history.extend(
        [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_reply},
        ]
    )
    save_chat_history(history)
    return assistant_reply


def main():
    launch_web_interface()

    print("========================================")
    print("""████╗  █████╗ █████╗ ████╗
██╔═██╗██╔══╝██╔══██╗██╔═██╗
█████╔╝████╗ ███████║█████╔╝
██╔═██╗██╔═╝ ██╔══██║██╔═██╗
█████╔╝█████╗██║  ██║██║  ██║
╚════╝ ╚════╝╚═╝  ╚═╝╚═╝  ╚═╝""")
    print(f"Loaded {len(ALL_FUNCTIONS)} tools: {list(ALL_FUNCTIONS.keys())}")
    print("BEAR PIPELINE ONLINE")
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

                reply = chat_with_bear_agent(user_input)
                print(f"\nBear: {reply}\n")
                print("-" * 40)

            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as error:
                print(f"\n[System Error: {error} - Chat is continuing...]\n")

    finally:
        llm_cache.close()


if __name__ == "__main__":
    main()
