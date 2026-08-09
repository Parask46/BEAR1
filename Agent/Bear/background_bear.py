import time
import random
import subprocess
import os
import sys
import json
import datetime
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
SYNC_CONFIG_FILE = os.path.join(CALENDAR_CREDS_DIR, "calendar_sync_config.json")
CALENDAR_SCHEDULE_NOTE = os.path.join(MEMORY_LONG_DIR, "Calendar_Schedule.md")

os.makedirs(TASKS_DIR, exist_ok=True)

if CALENDAR_CREDS_DIR not in sys.path:
    sys.path.insert(0, CALENDAR_CREDS_DIR)
try:
    import credentials as creds
except ImportError:
    creds = None


class DeviceHardwareMonitor:
    def get_status(self):
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged and battery.percent < 20:
            return "CRITICAL_BATTERY"
            
        cpu_usage = psutil.cpu_percent(interval=1)
        if cpu_usage > 85:
            return "HIGH_LOAD"
            
        return "OK"


def pop_bear_console():
    CREATE_NEW_CONSOLE = 0x00000010
    subprocess.Popen([sys.executable, AGENT_PATH], creationflags=CREATE_NEW_CONSOLE, cwd=BEAR_ROOT)


def process_task(task):
    try:
        response = ollama.chat(
            model='qwen3:8b',
            messages=[
                {'role': 'system', 'content': 'You are an ai agent, executing a scheduled background task. Output the results cleanly using Obsidian markdown format. No emojis.'},
                {'role': 'user', 'content': task['prompt']}
            ]
        )
        output = response['message']['content']
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        filename = f"TaskResult_{safe_title.replace(' ', '_')}_{timestamp}.md"
        filepath = os.path.join(TASKS_DIR, filename)
        
        md_content = f"---\ntags: [background-task, ai-generated]\ndate: {timestamp}\npriority: {task.get('priority', 3)}\n---\n# {task['title']}\n\n**Prompt:** {task['prompt']}\n\n---\n\n### Result\n{output}\n"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
            
    except Exception:
        pass


def load_sync_config():
    if os.path.exists(SYNC_CONFIG_FILE):
        try:
            with open(SYNC_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "sync_enabled": True,
        "sync_days_past": 7,
        "sync_days_ahead": 28,
        "categories": {"schoolwork": True, "homestuff": True, "events": True, "personal": True}
    }


def classify_calendar_events_with_llm(raw_events, config):
    """Uses Ollama to process all calendar events and classify them into categories."""
    if not raw_events:
        return

    active_categories = [cat for cat, enabled in config.get("categories", {}).items() if enabled]
    
    prompt = f"""You are a calendar sorting assistant. Analyze these raw calendar events and categorize each event into exactly ONE of these active categories:
{json.dumps(active_categories)}

Definitions:
- schoolwork: homework, assignments, studying, school projects, classes
- homestuff: chores, household tasks, family errands, home maintenance
- events: social outings, going out, parties, hangouts with friends
- personal: doctor appointments, personal care, medical, individual notes

Events List to classify:
{json.dumps(raw_events, indent=2)}

Output standard Markdown formatted specifically for Obsidian notes:
Start with frontmatter:
---
tags: [calendar, schedule, ai-sorted]
updated: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
---

# [[Calendar_Schedule|Calendar Schedule]]

For each active category, create a section `## [Category Name]`.
Inside each section, list the items as formatted bullet points:
`- **[Date/Time]** Event Title - Description (if any)`

If a category has no events, write `*No upcoming items.*` under that section.
Do not use emojis under any circumstances. Keep output structured and readable.
"""

    try:
        response = ollama.chat(
            model='qwen3:8b',
            messages=[
                {'role': 'system', 'content': 'You sort calendar events into structured markdown categories. Do not use emojis.'},
                {'role': 'user', 'content': prompt}
            ]
        )
        classified_md = response['message']['content']

        with open(CALENDAR_SCHEDULE_NOTE, 'w', encoding='utf-8') as f:
            f.write(classified_md)
            
    except Exception as e:
        pass


def sync_calendar_all():
    """Polls Apple Calendar, extracts all events within the configured window, and sorts them."""
    if not creds or not hasattr(creds, 'APPLE_ID') or not hasattr(creds, 'APP_PASSWORD'):
        return

    config = load_sync_config()
    if not config.get("sync_enabled", True):
        return

    try:
        client = caldav.DAVClient(url="https://caldav.icloud.com", username=creds.APPLE_ID, password=creds.APP_PASSWORD)
        principal = client.principal()
        calendars = principal.calendars()

        days_past = config.get("sync_days_past", 1)
        days_ahead = config.get("sync_days_ahead", 7)
        
        start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_past)
        end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_ahead)

        raw_events = []
        ai_tasks = []

        # Load existing background task queue
        tasks = []
        if os.path.exists(QUEUE_FILE):
            try:
                with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
            except Exception:
                tasks = []
        existing_titles = [t.get('title') for t in tasks]
        queued_new_task = False

        for calendar in calendars:
            try:
                events = calendar.date_search(start=start_time, end=end_time)
                for event in events:
                    ical_data = Calendar.from_ical(event.data)
                    for component in ical_data.walk():
                        if component.name == "VEVENT":
                            summary = str(component.get("summary", ""))
                            description = str(component.get("description", ""))
                            dtstart = component.get("dtstart").dt
                            dt_str = dtstart.isoformat() if hasattr(dtstart, 'isoformat') else str(dtstart)

                            # Handle explicit [AI Task] events for background tasks
                            if "[AI Task]" in summary:
                                if summary not in existing_titles:
                                    priority = 3
                                    if "Priority: 1" in description: priority = 1
                                    elif "Priority: 2" in description: priority = 2
                                    
                                    tasks.append({
                                        "task_id": len(tasks) + 1,
                                        "title": summary,
                                        "prompt": description.replace("Priority: 1", "").replace("Priority: 2", "").replace("Priority: 3", "").strip(),
                                        "priority": priority,
                                        "status": "pending",
                                        "scheduled_for": dt_str
                                    })
                                    existing_titles.append(summary)
                                    queued_new_task = True
                            else:
                                raw_events.append({
                                    "title": summary,
                                    "date_time": dt_str,
                                    "description": description
                                })
            except Exception:
                continue

        if queued_new_task:
            with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, indent=2)

        # Run AI sorting on standard calendar entries
        if raw_events:
            classify_calendar_events_with_llm(raw_events, config)

    except Exception:
        pass


def check_task_queue(monitor):
    if not os.path.exists(QUEUE_FILE):
        return
        
    try:
        with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except Exception:
        return
        
    now = datetime.datetime.now(datetime.timezone.utc)
    
    pending_tasks = []
    for t in tasks:
        if t.get('status') == 'pending':
            try:
                task_time = datetime.datetime.fromisoformat(t.get('scheduled_for').replace("Z", "+00:00"))
                if task_time.tzinfo is None:
                    task_time = task_time.replace(tzinfo=datetime.timezone.utc)
                    
                if task_time <= now:
                    pending_tasks.append(t)
            except Exception:
                pending_tasks.append(t)

    if not pending_tasks:
        return
        
    pending_tasks.sort(key=lambda x: x.get('priority', 3))
    status = monitor.get_status()
    updated = False
    
    for task in pending_tasks:
        if status == "HIGH_LOAD":
            break 
            
        if status == "CRITICAL_BATTERY" and task.get('priority', 3) > 1:
            continue 
            
        process_task(task)
        task['status'] = 'completed'
        updated = True
        status = monitor.get_status()
        
    if updated:
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2)


def start_lurking():
    monitor = DeviceHardwareMonitor()
    while True:
        # Sync and classify all calendar items (schoolwork, homestuff, events, personal)
        sync_calendar_all()
        
        # Process background tasks
        check_task_queue(monitor)
        
        # Random startup chance
        if random.random() < 0.10: 
            pop_bear_console()
            time.sleep(10800) 
            
        time.sleep(300) 


if __name__ == "__main__":
    start_lurking()