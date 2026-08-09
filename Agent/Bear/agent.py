import ollama
import datetime
import json
import os
import sys
import random
import time

# Setup Root and dynamically load ALL tools
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
if BEAR_ROOT not in sys.path:
    sys.path.append(BEAR_ROOT)

from TOOLS import tool_loader

# Get tools dynamically!
ALL_SCHEMAS, ALL_FUNCTIONS = tool_loader.get_all_tools()

# File Paths
MEMORY_DIR = os.path.join(BEAR_ROOT, 'MEMORY')
SHORT_TERM_FILE = os.path.join(MEMORY_DIR, 'chat_history.json')
LONG_TERM_DIR = os.path.join(MEMORY_DIR, 'MEMORY-LONG')
CHAT_ARCHIVE_DIR = os.path.join(LONG_TERM_DIR, 'CHAT')
AGENT_PROMPT_FILE = os.path.join(BEAR_ROOT, 'Agent', 'agentprompt.md')
MEMORY_PROMPT_FILE = os.path.join(MEMORY_DIR, 'memoryprompt.md')


def ensure_directories():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(LONG_TERM_DIR, exist_ok=True)
    os.makedirs(CHAT_ARCHIVE_DIR, exist_ok=True)

def load_file(filepath: str, default_text: str = "") -> str:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return default_text

def archive_chat_to_obsidian():
    if not os.path.exists(SHORT_TERM_FILE): return
    try:
        with open(SHORT_TERM_FILE, 'r', encoding='utf-8') as f:
            messages = json.load(f).get('messages', [])
    except Exception: return
    if len(messages) <= 1: return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_path = os.path.join(CHAT_ARCHIVE_DIR, f"Chat_{timestamp}.md")

    md_content = f"---\ntags: [chat-archive]\ndate: {timestamp}\n---\n# Chat Archive: {timestamp}\n\n"
    for msg in messages:
        if msg.get('role') == 'user':
            md_content += f"> [!info] You\n> {msg.get('content', '')}\n\n"
        elif msg.get('role') == 'assistant':
            md_content += f"**Bear Agent:**\n{msg.get('content', '')}\n\n---\n"

    with open(archive_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    os.remove(SHORT_TERM_FILE)
    print(f"\n[System: Chat archived to MEMORY-LONG\\CHAT\\Chat_{timestamp}.md]")

def load_chat_history():
    if os.path.exists(SHORT_TERM_FILE):
        try:
            with open(SHORT_TERM_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('messages', [])
        except Exception: pass
    return []

def save_chat_history(messages):
    # Filter out the tool calls and hidden system commands
    clean_messages = [m for m in messages if m.get('role') in ['user', 'assistant'] and not m.get('tool_calls')]
    
    # Keep only the last 8 messages (4 user prompts + 4 Bear responses)
    max_messages = 8
    short_history = clean_messages[-max_messages:]
    
    with open(SHORT_TERM_FILE, 'w', encoding='utf-8') as f:
        json.dump({'messages': short_history}, f, indent=2, ensure_ascii=False)

def trigger_startup_greeting():
    """Randomly decides if Bear should speak first when the script launches."""
    # 50% chance Bear starts the conversation. Change to 1.0 if you want it every time.
    if random.random() > 0.5:
        return

    print("\n[System: Bear is initiating conversation...]")
    
    agent_prompt = load_file(AGENT_PROMPT_FILE, "You are a helpful AI.")
    now = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")
    
    # Strict override to maintain the persona
    system_instruction = f"{agent_prompt}\n\n[SYSTEM CLOCK: {now}]\n\n***SYSTEM OVERRIDE: ZERO EMOJIS ALLOWED. NO YAPPING. Speak like a normal human.***"
    
    history = load_chat_history()
    messages = [{'role': 'system', 'content': system_instruction}] + history
    
    # The hidden prompt to trigger the proactive greeting
    messages.append({
        'role': 'user', 
        'content': "[System Command: You just met up with the user. Start the conversation naturally like a friend. Do not use emojis. Keep it to one or two sentences.]"
    })

    response = ollama.chat(
        model='qwen3:8b', 
        messages=messages
    )

    assistant_reply = response['message']['content']
    
    # Save only Bear's reply to history so the hidden system command isn't remembered
    history.append({'role': 'assistant', 'content': assistant_reply})
    save_chat_history(history)

    print(f"\nBear: {assistant_reply}\n")
    print("-" * 40)

def chat_with_bear_agent(user_prompt):
    agent_prompt = load_file(AGENT_PROMPT_FILE, "You are a helpful AI.")
    memory_prompt = load_file(MEMORY_PROMPT_FILE, "Use Obsidian syntax.")
    now = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")

    # 1. Fortify the system instruction with an absolute command for proactive memory
    system_instruction = f"{agent_prompt}\n\n### Memory Rules:\n{memory_prompt}\n\n[SYSTEM CLOCK: {now}]\n\n***SYSTEM OVERRIDE: ZERO EMOJIS ALLOWED. SPEAK LIKE A NORMAL HUMAN. NO YAPPING. ALWAYS BE PROACTIVE WITH MEMORY.***"
    
    history = load_chat_history()
    messages = [{'role': 'system', 'content': system_instruction}] + history
    
    # 2. The hidden trigger: Force Bear to evaluate memory usage on EVERY turn
    hidden_reminder = (
        "[System Reminder: 0 emojis allowed. Keep it brief and human. "
        "PROACTIVE MEMORY CHECK: If the user just stated a new fact, preference, or plan, YOU MUST use the write_note tool to save it right now. "
        "If you need to remember past context to answer, use the read_note tool before replying.]"
    )
    llm_user_content = f"{user_prompt}\n\n{hidden_reminder}"
    messages.append({'role': 'user', 'content': llm_user_content})

    # Call Ollama with dynamically loaded tools
    response = ollama.chat(
        model='qwen3:8b', 
        messages=messages, 
        tools=ALL_SCHEMAS if ALL_SCHEMAS else None
    )

    if response.get('message', {}).get('tool_calls'):
        messages.append(response['message'])
        for tool_call in response['message']['tool_calls']:
            func_name = tool_call['function']['name']
            args = tool_call['function']['arguments']

            if func_name in ALL_FUNCTIONS:
                print(f"[System: Executing dynamic tool -> {func_name}]")
                result = ALL_FUNCTIONS[func_name](**args)
                messages.append({'role': 'tool', 'name': func_name, 'content': str(result)})

        # 2nd call after tool execution
        response = ollama.chat(model='qwen3:8b', messages=messages)

    assistant_reply = response['message']['content']
    
    # 3. Save the CLEAN user prompt to history, not the one with the hidden reminder
    history.append({'role': 'user', 'content': user_prompt})
    history.append({'role': 'assistant', 'content': assistant_reply})
    save_chat_history(history)

    return assistant_reply


if __name__ == "__main__":
    ensure_directories()
    print("========================================")
    print("""████╗  █████╗ █████╗ ████╗ 
██╔═██╗██╔══╝██╔══██╗██╔═██╗
█████╔╝████╗ ███████║█████╔╝
██╔═██╗██╔═╝ ██╔══██║██╔═██╗
█████╔╝█████╗██║  ██║██║  ██║
╚════╝ ╚════╝╚═╝  ╚═╝╚═╝  ╚═╝ """)
    print(f"Loaded {len(ALL_FUNCTIONS)} tools: {list(ALL_FUNCTIONS.keys())}")
    print("========================================\n")

    # Bear decides whether to speak first
    trigger_startup_greeting()

    while True:
        user_input = input("You: ").strip()
        if not user_input: continue
        if user_input.lower() in ['exit', 'quit', 'clear']:
            archive_chat_to_obsidian()
            if user_input.lower() != 'clear':
                print("Shutting down...")
                break
            continue
        
        reply = chat_with_bear_agent(user_input)
        print(f"\nBear: {reply}\n")
        print("-" * 40)