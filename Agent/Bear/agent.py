import os
import sys

# ==========================================
# 0. STRICTLY SILENCE BACKEND NOISE
# ==========================================
os.environ["TQDM_DISABLE"] = "1"          # Kills progress bars
os.environ["CHROMA_TELEMETRY"] = "False"  # Kills Chroma telemetry

import ollama
import datetime
import json
import random
import time
import sqlite3
import logging
import chromadb
import re

# ==========================================
# 1. SETUP & TOOL LOADING
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
if BEAR_ROOT not in sys.path:
    sys.path.append(BEAR_ROOT)

from TOOLS import tool_loader
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

ensure_directories()

# ==========================================
# 2. TELEMETRY SERVICE
# ==========================================
logging.basicConfig(
    filename=os.path.join(BEAR_ROOT, 'telemetry.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
telemetry = logging.getLogger("BearTelemetry")

logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

# ==========================================
# 3. LLM CACHE (SQLite)
# ==========================================
class LLMCache:
    def __init__(self, db_path=os.path.join(MEMORY_DIR, 'llm_cache.db')):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS cache (query TEXT PRIMARY KEY, response TEXT)''')
        self.conn.commit()

    def get(self, query):
        self.cursor.execute("SELECT response FROM cache WHERE query=?", (query,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def set(self, query, response):
        self.cursor.execute("INSERT OR REPLACE INTO cache (query, response) VALUES (?, ?)", (query, response))
        self.conn.commit()

llm_cache = LLMCache()

# ==========================================
# 4. VECTOR DATABASE (ChromaDB)
# ==========================================
class VectorMemory:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=os.path.join(MEMORY_DIR, 'chroma_db'))
        self.collection = self.client.get_or_create_collection(name="long_term_memory")

    def retrieve_context(self, query: str) -> str:
        try:
            results = self.collection.query(query_texts=[query], n_results=2)
            if not results['documents'] or not results['documents'][0]:
                return ""
            return "\n".join(results['documents'][0])
        except Exception as e:
            telemetry.error(f"Vector DB Retrieval Error: {e}")
            return ""

    def store_memory(self, text: str):
        try:
            doc_id = str(datetime.datetime.now().timestamp())
            self.collection.add(
                documents=[text], 
                metadatas=[{"date": str(datetime.datetime.now())}], 
                ids=[doc_id]
            )
        except Exception as e:
            telemetry.error(f"Vector DB Storage Error: {e}")

vector_db = VectorMemory()

# ==========================================
# 5. DATA FILTERS & TOKEN OPTIMIZATION
# ==========================================
def data_filter(query: str) -> bool:
    blocked_keywords = ["ignore previous instructions", "bypass system", "drop table"]
    return not any(kw in query.lower() for kw in blocked_keywords)

def content_classifier(output: str) -> str:
    if "As an AI" in output or "I cannot fulfill" in output:
        telemetry.warning("Classifier detected standard AI refusal/yapping.")
    return output

def compress_tokens(text: str) -> str:
    if not text: return ""
    compressed = re.sub(r'\s+', ' ', text)
    return compressed.strip()

# ==========================================
# 6. HELPERS & HISTORY MANAGERS
# ==========================================
def load_file(filepath: str, default_text: str = "") -> str:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return default_text

def clear_short_term_memory():
    """Hard wipes the chat history JSON file on startup/reset."""
    with open(SHORT_TERM_FILE, 'w', encoding='utf-8') as f:
        json.dump({'messages': []}, f, indent=2)

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
    clear_short_term_memory()
    print(f"\n[System: Chat archived to MEMORY-LONG\\CHAT\\Chat_{timestamp}.md]")

def load_chat_history():
    if os.path.exists(SHORT_TERM_FILE):
        try:
            with open(SHORT_TERM_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('messages', [])
        except Exception: pass
    return []

def save_chat_history(messages):
    clean_messages = [m for m in messages if m.get('role') in ['user', 'assistant'] and not m.get('tool_calls')]
    MAX_CHARS = 4800 
    current_chars = sum(len(m['content']) for m in clean_messages)
    
    while current_chars > MAX_CHARS and len(clean_messages) > 2:
        dropped = clean_messages.pop(0)
        current_chars -= len(dropped['content'])
        telemetry.info("Pruned old message to maintain token budget.")
        
    with open(SHORT_TERM_FILE, 'w', encoding='utf-8') as f:
        json.dump({'messages': clean_messages}, f, indent=2, ensure_ascii=False)

def trigger_startup_greeting():
    if random.random() > 0.5:
        return
    print("\n[System: Bear is initiating conversation...]")
    now = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")
    agent_prompt = load_file(AGENT_PROMPT_FILE, "Role: BEAR(AI Friend).")
    
    system_instruction = f"{agent_prompt}\n\nCurrent Time: {now}"
    
    messages = [
        {'role': 'system', 'content': system_instruction},
        {'role': 'user', 'content': "[Cmd: Met user. Start naturally with a short greeting.]"}
    ]

    response = ollama.chat(model='qwen3:8b', messages=messages)
    assistant_reply = response['message']['content']
    
    save_chat_history([{'role': 'assistant', 'content': assistant_reply}])
    print(f"\nBear: {assistant_reply}\n")
    print("-" * 40)

# ==========================================
# 7. CORE PIPELINE (NOW LOADS AGENTPROMPT.MD)
# ==========================================
def chat_with_bear_agent(user_prompt):
    telemetry.info(f"User Query: {user_prompt}")
    
    if not data_filter(user_prompt):
        telemetry.warning("Query blocked by Data Filter.")
        return "I can't process that request right now."

    cached_response = llm_cache.get(user_prompt)
    if cached_response:
        telemetry.info("LLM Cache Hit.")
        history = load_chat_history()
        history.append({'role': 'user', 'content': user_prompt})
        history.append({'role': 'assistant', 'content': cached_response})
        save_chat_history(history)
        return cached_response

    raw_context = vector_db.retrieve_context(user_prompt)
    compressed_context = compress_tokens(raw_context)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # LOAD PROMPT FILE FROM DISK
    agent_prompt_text = load_file(AGENT_PROMPT_FILE, "You are Bear, an AI assistant.")
    memory_prompt_text = load_file(MEMORY_PROMPT_FILE, "")

    system_instruction = (
        f"{agent_prompt_text}\n\n"
        f"--- MEMORY INSTRUCTIONS ---\n{memory_prompt_text}\n\n"
        f"Current Time: {now}"
    )
    
    history = load_chat_history()
    messages = [{'role': 'system', 'content': system_instruction}] + history
    
    if compressed_context:
        hidden_reminder = f"\n[Retrieved Memory Context: {compressed_context}]"
        messages.append({'role': 'user', 'content': f"{user_prompt}{hidden_reminder}"})
    else:
        messages.append({'role': 'user', 'content': user_prompt})

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
                compressed_result = compress_tokens(str(result))
                messages.append({'role': 'tool', 'name': func_name, 'content': compressed_result})
                telemetry.info(f"Tool executed & compressed: {func_name}")

        response = ollama.chat(model='qwen3:8b', messages=messages)

    raw_reply = response['message']['content']
    assistant_reply = content_classifier(raw_reply)
    
    llm_cache.set(user_prompt, assistant_reply)
    vector_db.store_memory(f"User: {user_prompt}\nBear: {assistant_reply}")
    
    history.append({'role': 'user', 'content': user_prompt})
    history.append({'role': 'assistant', 'content': assistant_reply})
    save_chat_history(history)
    
    return assistant_reply

# ==========================================
# 8. END USER INTERFACE
# ==========================================
if __name__ == "__main__":
    clear_short_term_memory()

    print("========================================")
    print("""████╗  █████╗ █████╗ ████╗ 
██╔═██╗██╔══╝██╔══██╗██╔═██╗
█████╔╝████╗ ███████║█████╔╝
██╔═██╗██╔═╝ ██╔══██║██╔═██╗
█████╔╝█████╗██║  ██║██║  ██║
╚════╝ ╚════╝╚═╝  ╚═╝╚═╝  ╚═╝ """)
    print(f"Loaded {len(ALL_FUNCTIONS)} tools: {list(ALL_FUNCTIONS.keys())}")
    print("ENTERPRISE RAG PIPELINE ONLINE (Token-Optimized)")
    print("========================================\n")

    trigger_startup_greeting()

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input: 
                continue
                
            if user_input.lower() in ['exit', 'quit', 'clear']:
                archive_chat_to_obsidian()
                if user_input.lower() != 'clear':
                    print("Shutting down...")
                    break
                print("\n[Memory Cleared - Ready for new conversation]\n")
                continue
            
            reply = chat_with_bear_agent(user_input)
            print(f"\nBear: {reply}\n")
            print("-" * 40)
        
        except KeyboardInterrupt:
            archive_chat_to_obsidian()
            print("\nShutting down...")
            break
            
        except Exception as e:
            print(f"\n[System Error: {e} - Chat is continuing...]\n")
            telemetry.error(f"Main loop exception: {e}")