import urllib.request
import urllib.parse
import json

def get_current_weather(location: str) -> str:
    """Fetches coordinates for a location and gets the current weather."""
    try:
        # 1. Geocode the location (turn city name into latitude/longitude)
        safe_location = urllib.parse.quote(location)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={safe_location}&count=1&language=en&format=json"
        
        with urllib.request.urlopen(geo_url) as response:
            geo_data = json.loads(response.read().decode())
        
        if 'results' not in geo_data or not geo_data['results']:
            return f"Error: Could not find coordinates for {location}."
        
        lat = geo_data['results'][0]['latitude']
        lon = geo_data['results'][0]['longitude']
        resolved_name = f"{geo_data['results'][0]['name']}, {geo_data['results'][0].get('country', '')}"
        
        # 2. Fetch the weather using the coordinates
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        
        with urllib.request.urlopen(weather_url) as response:
            weather_data = json.loads(response.read().decode())
        
        current = weather_data.get('current_weather', {})
        temp = current.get('temperature', 'N/A')
        windspeed = current.get('windspeed', 'N/A')
        
        return f"The current weather in {resolved_name} is {temp}°C with wind speeds of {windspeed} km/h."
        
    except Exception as e:
        return f"Error fetching weather data: {str(e)}"