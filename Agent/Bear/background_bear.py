import os
import sys
import json
import time
import random
import hashlib
import datetime
import subprocess

import psutil
import ollama
import caldav
from icalendar import Calendar

BEAR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_PATH = os.path.join(BEAR_ROOT, "Agent", "Bear", "agent.py")
QUEUE_FILE = os.path.join(BEAR_ROOT, "MEMORY", "task_queue.json")
TASKS_DIR = os.path.join(BEAR_ROOT, "MEMORY", "MEMORY-LONG", "TASKS")
MEMORY_LONG_DIR = os.path.join(BEAR_ROOT, "MEMORY", "MEMORY-LONG")
CALENDAR_CREDS_DIR = os.path.join(BEAR_ROOT, "TOOLS", "apple_calendar")
SYNC_CONFIG_FILE = os.path.join(
    CALENDAR_CREDS_DIR,
    "calendar_sync_config.json",
)
CALENDAR_SCHEDULE_NOTE = os.path.join(
    MEMORY_LONG_DIR,
    "Calendar_Schedule.md",
)

LLM_MODEL = "qwen3:8b"
SYNC_INTERVAL_SECONDS = 300
CONSOLE_POP_CHANCE = 0.10
CONSOLE_COOLDOWN_SECONDS = 10800

os.makedirs(TASKS_DIR, exist_ok=True)

if CALENDAR_CREDS_DIR not in sys.path:
    sys.path.insert(0, CALENDAR_CREDS_DIR)

try:
    import credentials as creds
except ImportError:
    creds = None


class DeviceHardwareMonitor:
    def __init__(self, cache_seconds=5):
        self.cache_seconds = cache_seconds
        self.last_check = 0.0
        self.last_status = "OK"
        psutil.cpu_percent(interval=None)

    def get_status(self):
        now = time.time()
        if now - self.last_check < self.cache_seconds:
            return self.last_status

        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged and battery.percent < 20:
            self.last_status = "CRITICAL_BATTERY"
        else:
            cpu_usage = psutil.cpu_percent(interval=None)
            self.last_status = "HIGH_LOAD" if cpu_usage > 85 else "OK"

        self.last_check = now
        return self.last_status


def pop_bear_console():
    create_new_console = 0x00000010
    subprocess.Popen(
        [sys.executable, AGENT_PATH],
        creationflags=create_new_console,
        cwd=BEAR_ROOT,
    )


from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

# Define State
class TaskState(TypedDict):
    task_title: str
    prompt: str
    plan: str
    result: str

# Node 1: Planner
def plan_node(state: TaskState):
    llm = ChatOllama(model=LLM_MODEL)
    prompt = ChatPromptTemplate.from_template("Plan how to execute this background task step-by-step: {task}. Prompt: {prompt}")
    plan = llm.invoke(prompt.format(task=state["task_title"], prompt=state["prompt"])).content
    return {"plan": plan}

# Node 2: Executor
def execute_node(state: TaskState):
    llm = ChatOllama(model=LLM_MODEL)
    prompt = ChatPromptTemplate.from_template("Execute the task based on this plan:\n{plan}\n\nTask: {task}. Output the result cleanly in Obsidian Markdown. No emojis.")
    result = llm.invoke(prompt.format(plan=state["plan"], task=state["task_title"])).content
    return {"result": result}

# Build LangGraph Workflow
workflow = StateGraph(TaskState)
workflow.add_node("planner", plan_node)
workflow.add_node("executor", execute_node)
workflow.set_entry_point("planner")
workflow.add_edge("planner", "executor")
workflow.add_edge("executor", END)
task_app = workflow.compile()

def process_task(task):
    """Replaces the old process_task with LangGraph execution."""
    initial_state = {
        "task_title": task["title"],
        "prompt": task["prompt"],
        "plan": "",
        "result": ""
    }
    
    # Run the multi-step agent workflow
    final_state = task_app.invoke(initial_state)
    output = final_state["result"]

    # Save to Markdown
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = "".join(c for c in task["title"] if c.isalnum() or c == " ").strip()
    filename = f"TaskResult_{safe_title.replace(' ', '_')}_{timestamp}.md"
    filepath = os.path.join(TASKS_DIR, filename)

    markdown = (
        "---\n"
        "tags: [background-task, ai-generated]\n"
        f"date: {timestamp}\n"
        f"priority: {task.get('priority', 3)}\n"
        "---\n"
        f"# {task['title']}\n\n"
        f"**Plan Strategy:**\n{final_state['plan']}\n\n"
        "---\n\n"
        "### Result\n"
        f"{output}\n"
    )

    with open(filepath, "w", encoding="utf-8") as file:
        file.write(markdown)


def load_sync_config():
    default_config = {
        "sync_enabled": True,
        "sync_days_past": 1,
        "sync_days_ahead": 7,
        "categories": {
            "schoolwork": True,
            "homestuff": True,
            "events": True,
            "personal": True,
        },
    }

    if not os.path.exists(SYNC_CONFIG_FILE):
        return default_config

    try:
        with open(SYNC_CONFIG_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default_config


def events_hash(events):
    content = json.dumps(events, sort_keys=True).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


last_events_hash = None


def classify_calendar_events_with_llm(raw_events, config):
    global last_events_hash

    if not raw_events:
        return

    current_hash = events_hash(raw_events)
    if current_hash == last_events_hash:
        return

    active_categories = [
        category
        for category, enabled in config.get("categories", {}).items()
        if enabled
    ]

    prompt = f"""You are a calendar sorting assistant. Categorize each event into exactly ONE active category:
{json.dumps(active_categories)}

Definitions:
- schoolwork: homework, assignments, studying, school projects, classes
- homestuff: chores, household tasks, family errands, home maintenance
- events: social outings, parties, hangouts, concerts, and leisure
- personal: appointments, self-care, medical, and personal reminders

Events:
{json.dumps(raw_events, indent=2)}

Output Obsidian Markdown using this frontmatter:
---
tags: [calendar, schedule, ai-sorted]
updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
---

# [[Calendar_Schedule|Calendar Schedule]]

Create a section for every active category. Use this format:
- **[Date/Time]** Event Title - Description

If a category has no events, write: *No upcoming items.*
Do not use emojis."""

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Sort calendar events into structured Markdown. Do not use emojis.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    with open(CALENDAR_SCHEDULE_NOTE, "w", encoding="utf-8") as file:
        file.write(response["message"]["content"])

    last_events_hash = current_hash


def sync_calendar_all():
    if not creds:
        return
    if not hasattr(creds, "APPLE_ID") or not hasattr(creds, "APP_PASSWORD"):
        return

    config = load_sync_config()
    if not config.get("sync_enabled", True):
        return

    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=creds.APPLE_ID,
        password=creds.APP_PASSWORD,
    )
    principal = client.principal()
    calendars = principal.calendars()

    days_past = config.get("sync_days_past", 1)
    days_ahead = config.get("sync_days_ahead", 7)
    start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=days_past
    )
    end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=days_ahead
    )

    raw_events = []
    tasks = []

    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as file:
                tasks = json.load(file)
        except (OSError, json.JSONDecodeError):
            tasks = []

    existing_titles = {task.get("title") for task in tasks}
    queued_new_task = False

    for calendar in calendars:
        try:
            events = calendar.date_search(start=start_time, end=end_time)
            for event in events:
                calendar_data = Calendar.from_ical(event.data)
                for component in calendar_data.walk():
                    if component.name != "VEVENT":
                        continue

                    summary = str(component.get("summary", ""))
                    description = str(component.get("description", ""))
                    start_component = component.get("dtstart")
                    if start_component is None:
                        continue

                    start_value = start_component.dt
                    start_string = (
                        start_value.isoformat()
                        if hasattr(start_value, "isoformat")
                        else str(start_value)
                    )

                    if "[AI Task]" in summary:
                        if summary in existing_titles:
                            continue

                        priority = 3
                        if "Priority: 1" in description:
                            priority = 1
                        elif "Priority: 2" in description:
                            priority = 2

                        prompt = description
                        for marker in ("Priority: 1", "Priority: 2", "Priority: 3"):
                            prompt = prompt.replace(marker, "")

                        tasks.append(
                            {
                                "task_id": len(tasks) + 1,
                                "title": summary,
                                "prompt": prompt.strip(),
                                "priority": priority,
                                "status": "pending",
                                "scheduled_for": start_string,
                            }
                        )
                        existing_titles.add(summary)
                        queued_new_task = True
                    else:
                        raw_events.append(
                            {
                                "title": summary,
                                "date_time": start_string,
                                "description": description,
                            }
                        )
        except Exception:
            continue

    if queued_new_task:
        with open(QUEUE_FILE, "w", encoding="utf-8") as file:
            json.dump(tasks, file, indent=2)

    if raw_events:
        classify_calendar_events_with_llm(raw_events, config)


def check_task_queue(monitor):
    if not os.path.exists(QUEUE_FILE):
        return

    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as file:
            tasks = json.load(file)
    except (OSError, json.JSONDecodeError):
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    pending_tasks = []

    for task in tasks:
        if task.get("status") != "pending":
            continue

        try:
            scheduled_for = task.get("scheduled_for", "")
            task_time = datetime.datetime.fromisoformat(
                scheduled_for.replace("Z", "+00:00")
            )
            if task_time.tzinfo is None:
                task_time = task_time.replace(tzinfo=datetime.timezone.utc)
            if task_time <= now:
                pending_tasks.append(task)
        except (TypeError, ValueError):
            pending_tasks.append(task)

    pending_tasks.sort(key=lambda task: task.get("priority", 3))
    status = monitor.get_status()
    changed = False

    for task in pending_tasks:
        if status == "HIGH_LOAD":
            break
        if status == "CRITICAL_BATTERY" and task.get("priority", 3) > 1:
            continue

        try:
            process_task(task)
            task["status"] = "completed"
            changed = True
        except Exception:
            task["status"] = "failed"
            changed = True

        status = monitor.get_status()

    if changed:
        with open(QUEUE_FILE, "w", encoding="utf-8") as file:
            json.dump(tasks, file, indent=2)


def start_lurking():
    monitor = DeviceHardwareMonitor()
    console_cooldown_until = 0.0

    while True:
        loop_start = time.time()

        try:
            sync_calendar_all()
        except Exception:
            pass

        try:
            check_task_queue(monitor)
        except Exception:
            pass

        current_time = time.time()
        if (
            current_time >= console_cooldown_until
            and random.random() < CONSOLE_POP_CHANCE
        ):
            try:
                pop_bear_console()
            except Exception:
                pass
            console_cooldown_until = current_time + CONSOLE_COOLDOWN_SECONDS

        elapsed = time.time() - loop_start
        time.sleep(max(0, SYNC_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    start_lurking()