import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
LONG_TERM_DIR = os.path.join(BEAR_ROOT, 'MEMORY', 'MEMORY-LONG')

def write_note(filename: str, content: str) -> str:
    os.makedirs(LONG_TERM_DIR, exist_ok=True)
    if not filename.endswith('.md'):
        filename += '.md'
    filepath = os.path.join(LONG_TERM_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Success: Saved {filename} to long-term memory."

def read_note(filename: str) -> str:
    if not filename.endswith('.md'):
        filename += '.md'
    filepath = os.path.join(LONG_TERM_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return f"Error: Note {filename} does not exist."