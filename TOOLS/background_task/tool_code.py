import os
import sys
import json

# Force Python to see BEAR_ROOT so we can import the calendar tool
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BEAR_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
if BEAR_ROOT not in sys.path:
    sys.path.append(BEAR_ROOT)

try:
    from TOOLS.apple_calendar.tool_code import add_apple_calendar_event
except ImportError:
    add_apple_calendar_event = None

QUEUE_FILE = os.path.join(BEAR_ROOT, 'MEMORY', 'task_queue.json')

def add_background_task(title: str, prompt: str, priority: int, start_time: str, end_time: str) -> str:
    """Queues a task for the background worker and adds it to Apple Calendar."""
    
    # 1. Save to internal JSON queue
    tasks = []
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
        except Exception:
            pass

    task_id = len(tasks) + 1
    tasks.append({
        "task_id": task_id,
        "title": title,
        "prompt": prompt,
        "priority": priority,
        "status": "pending",
        "scheduled_for": start_time
    })

    with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, indent=2)

    # 2. Add to Apple Calendar
    cal_msg = "(Calendar sync failed: Tool not found)"
    if add_apple_calendar_event:
        cal_msg = add_apple_calendar_event(
            title=f"[AI Task] {title}",
            start_time=start_time,
            end_time=end_time,
            description=f"Priority: {priority}\nPrompt: {prompt}"
        )

    return f"Task '{title}' queued successfully. {cal_msg}"