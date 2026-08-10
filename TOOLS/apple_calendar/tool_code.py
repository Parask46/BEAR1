import os
import sys
import datetime
import uuid
import caldav
from icalendar import Calendar, Event

# Force Python to see the folder this script is in so the import cannot fail
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Now it will absolutely find credentials.py
try:
    import credentials as creds
except ImportError as e:
    creds = None

def get_apple_calendar_events(days_ahead: int = 7) -> str:
    """Fetches upcoming events from Apple Calendar (iCloud) via CalDAV."""
    if not creds or not hasattr(creds, 'APPLE_ID') or not hasattr(creds, 'APP_PASSWORD'):
        return "Error: credentials.py is missing or does not have APPLE_ID and APP_PASSWORD set."
    
    username = creds.APPLE_ID
    password = creds.APP_PASSWORD
    url = "https://caldav.icloud.com"
    
    try:
        client = caldav.DAVClient(url=url, username=username, password=password)
        principal = client.principal()
        calendars = principal.calendars()
        
        start_time = datetime.datetime.now(datetime.timezone.utc)
        end_time = start_time + datetime.timedelta(days=days_ahead)
        
        parsed_events = []
        
        for calendar in calendars:
            try:
                events = calendar.date_search(start=start_time, end=end_time)
                for event in events:
                    ical_data = Calendar.from_ical(event.data)
                    for component in ical_data.walk():
                        if component.name == "VEVENT":
                            summary = str(component.get("summary", "No Title"))
                            dtstart = component.get("dtstart").dt
                            dtend = component.get("dtend").dt if component.get("dtend") else dtstart
                            
                            start_str = dtstart.isoformat() if hasattr(dtstart, 'isoformat') else str(dtstart)
                            end_str = dtend.isoformat() if hasattr(dtend, 'isoformat') else str(dtend)
                            
                            parsed_events.append({
                                "start_raw": str(dtstart),
                                "text": f"- [{calendar.name}] {summary} (Starts: {start_str}, Ends: {end_str})"
                            })
            except Exception:
                continue
        
        parsed_events.sort(key=lambda x: x["start_raw"])
        
        if not parsed_events:
            return f"No upcoming events found for the next {days_ahead} days."
        
        result = f"Upcoming Events (Next {days_ahead} days):\n"
        for e in parsed_events:
            result += e["text"] + "\n"
            
        return result
        
    except Exception as e:
        return f"CalDAV Connection Error: {str(e)}"

def add_apple_calendar_event(title: str, start_time: str, end_time: str, description: str = "") -> str:
    """Creates a new event in Apple Calendar (iCloud) via CalDAV."""
    if not creds or not hasattr(creds, 'APPLE_ID') or not hasattr(creds, 'APP_PASSWORD'):
        return "Error: credentials.py is missing or does not have APPLE_ID and APP_PASSWORD set."
    
    # Parse the ISO datetime strings provided by the AI
    try:
        start_dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        
        # Ensure they are timezone aware (defaulting to UTC if not specified)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return "Error: Start and end times must be valid ISO 8601 format (e.g., 2026-08-10T15:00:00)."

    username = creds.APPLE_ID
    password = creds.APP_PASSWORD
    url = "https://caldav.icloud.com"
    
    try:
        client = caldav.DAVClient(url=url, username=username, password=password)
        principal = client.principal()
        calendars = principal.calendars()
        
        if not calendars:
            return "Error: No calendars found on this account to write to."
            
        # Write to the user's first available calendar
        target_calendar = calendars[0]
        
        # Build the iCalendar data
        cal = Calendar()
        cal.add('prodid', '-//Bear Agent//EN')
        cal.add('version', '2.0')
        
        event = Event()
        event.add('summary', title)
        event.add('dtstart', start_dt)
        event.add('dtend', end_dt)
        event.add('dtstamp', datetime.datetime.now(datetime.timezone.utc))
        event.add('uid', str(uuid.uuid4()))
        if description:
            event.add('description', description)
            
        cal.add_component(event)
        
        # Save the event to iCloud
        target_calendar.save_event(cal.to_ical())
        
        return f"Success! '{title}' has been added to your calendar starting at {start_dt.strftime('%Y-%m-%d %H:%M')}."
        
    except Exception as e:
        return f"CalDAV Connection Error while creating event: {str(e)}"