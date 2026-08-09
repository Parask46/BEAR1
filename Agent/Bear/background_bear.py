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

BEAR_ROOT = os.path.abspath(os.path.dirname(__file__))
AGENT_PATH = os.path.join(BEAR_ROOT, "Agent", "Bear", "agent.py")
QUEUE_FILE = os.path.join(BEAR_ROOT, "MEMORY", "task_queue.json")
TASKS_DIR = os.path.join(BEAR_ROOT, "MEMORY", "MEMORY-LONG", "TASKS")
CALENDAR_CREDS = os.path.join(BEAR_ROOT, "TOOLS", "apple_calendar")

os.makedirs(TASKS_DIR, exist_ok=True)

# Dynamically load calendar credentials
if CALENDAR_CREDS not in sys.path:
    sys.path.insert(0, CALENDAR_CREDS)
try:
    import credentials as creds
except ImportError:
    creds = None


class DeviceHardwareMonitor:
    def get_status(self):
        """Checks real system vitals using psutil."""
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged and battery.percent < 20:
            return "CRITICAL_BATTERY"
            
        cpu_usage = psutil.cpu_percent(interval=1)
        if cpu_usage > 85:
            return "HIGH_LOAD"
            
        return "OK"

def pop_bear_console():
    """Forces a new visible command prompt window to open."""
    CREATE_NEW_CONSOLE = 0x00000010
    subprocess.Popen([sys.executable, AGENT_PATH], creationflags=CREATE_NEW_CONSOLE, cwd=BEAR_ROOT)

def process_task(task):
    """Executes the LLM task silently and saves to Obsidian memory."""
    try:
        response = ollama.chat(
            model='qwen3:8b',
            messages=[
                {'role': 'system', 'content': 'You are Bear, executing a scheduled background task. Output the results cleanly using Obsidian markdown format. No emojis.'},
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
            
    except Exception as e:
        pass 

def sync_calendar_tasks():
    """Polls Apple Calendar for new [AI Task] events created by the user and queues them."""
    if not creds or not hasattr(creds, 'APPLE_ID') or not hasattr(creds, 'APP_PASSWORD'):
        return
        
    try:
        # Load existing queue to prevent duplicates
        tasks = []
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
                
        existing_titles = [t.get('title') for t in tasks]

        # Connect to iCloud
        client = caldav.DAVClient(url="https://caldav.icloud.com", username=creds.APPLE_ID, password=creds.APP_PASSWORD)
        principal = client.principal()
        calendars = principal.calendars()
        
        # Look for events today and in the next 3 days
        start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        end_time = start_time + datetime.timedelta(days=4)
        
        queued_new = False
        
        for calendar in calendars:
            try:
                events = calendar.date_search(start=start_time, end=end_time)
                for event in events:
                    ical_data = Calendar.from_ical(event.data)
                    for component in ical_data.walk():
                        if component.name == "VEVENT":
                            summary = str(component.get("summary", ""))
                            
                            # Identify AI Tasks from the calendar
                            if "[AI Task]" in summary and summary not in existing_titles:
                                description = str(component.get("description", "Please run this background task."))
                                dtstart = component.get("dtstart").dt
                                
                                # Default priority to 3 if not specified in notes
                                priority = 3
                                if "Priority: 1" in description: priority = 1
                                elif "Priority: 2" in description: priority = 2
                                
                                tasks.append({
                                    "task_id": len(tasks) + 1,
                                    "title": summary,
                                    "prompt": description.replace("Priority: 1", "").replace("Priority: 2", "").replace("Priority: 3", "").strip(),
                                    "priority": priority,
                                    "status": "pending",
                                    "scheduled_for": dtstart.isoformat() if hasattr(dtstart, 'isoformat') else str(dtstart)
                                })
                                existing_titles.append(summary)
                                queued_new = True
            except Exception:
                continue

        if queued_new:
            with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, indent=2)

    except Exception:
        pass # Fail silently so the background loop doesn't crash

def check_task_queue(monitor):
    """Reads queue, checks vitals, and executes tasks based on time and priority."""
    if not os.path.exists(QUEUE_FILE):
        return
        
    try:
        with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except Exception:
        return
        
    # Only grab pending tasks whose scheduled time has arrived or passed
    now = datetime.datetime.now(datetime.timezone.utc)
    
    pending_tasks = []
    for t in tasks:
        if t.get('status') == 'pending':
            try:
                # Handle timezone parsing flexibly
                task_time = datetime.datetime.fromisoformat(t.get('scheduled_for').replace("Z", "+00:00"))
                if task_time.tzinfo is None:
                    task_time = task_time.replace(tzinfo=datetime.timezone.utc)
                    
                if task_time <= now:
                    pending_tasks.append(t)
            except Exception:
                # If time parsing fails, queue it to run immediately
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
        # 1. Sync any new tasks the user added directly from their iPhone Calendar
        sync_calendar_tasks()
        
        # 2. Process any pending background tasks quietly
        check_task_queue(monitor)
        
        # 3. Check if we should pop up and talk to the user
        if random.random() < 0.10: 
            pop_bear_console()
            time.sleep(10800) 
            
        time.sleep(60) 

if __name__ == "__main__":
    start_lurking()