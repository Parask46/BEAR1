import os
import subprocess

def execute_shell_command(command: str) -> str:
    """Executes a terminal/shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout if result.returncode == 0 else result.stderr
        return output.strip() if output else "Command executed with no output."
    except Exception as e:
        return f"Shell Execution Error: {str(e)}"

def read_local_file(filepath: str) -> str:
    """Reads a file from local disk."""
    if not os.path.exists(filepath):
        return f"Error: File '{filepath}' does not exist."
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception as e:
        return f"File Read Error: {str(e)}"

def write_local_file(filepath: str, content: str) -> str:
    """Writes text content to a specified path."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote file to {filepath}"
    except Exception as e:
        return f"File Write Error: {str(e)}"

def list_directory(path: str = ".") -> str:
    """Lists files and directories at path."""
    try:
        items = os.listdir(path)
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Directory Listing Error: {str(e)}"