"""
AQI Dashboard - Data Collector
Fetches AQI (WAQI) + Weather (OpenWeatherMap) data for Indian cities
and saves it into a CSV file (one row appended per run, per city).

HOW TO USE:
1. Fill in your WAQI_TOKEN and OWM_API_KEY below.
2. Run this script: python aqi_data_collector.py
3. Each run appends fresh rows to aqi_data.csv
4. Schedule this script to run every 15-30 min (Task Scheduler / cron /
   GitHub Actions) to build up a live time-series dataset.
"""

import requests
import csv
import os
import time
from datetime import datetime

# ---------------- CONFIG ----------------
# Keys are read from environment variables (set as GitHub Actions secrets).
# For local testing, you can temporarily hardcode them here instead, e.g.:
# WAQI_TOKEN = "your_token_here"
WAQI_TOKEN = os.environ.get("WAQI_TOKEN", "PASTE_YOUR_WAQI_TOKEN_HERE")
OWM_API_KEY = os.environ.get("OWM_API_KEY", "PASTE_YOUR_OPENWEATHERMAP_KEY_HERE")

CSV_FILE = "aqi_data.csv"

# City -> State mapping (used later for "most polluted state" analysis)
# lat/lon included for the India map visual in Power BI
CITIES = [
    {"city": "Delhi",      "state": "Delhi",          "lat": 28.6139, "lon": 77.2090},
    {"city": "Mumbai",     "state": "Maharashtra",    "lat": 19.0760, "lon": 72.8777},
    {"city": "Bangalore",  "state": "Karnataka",      "lat": 12.9716, "lon": 77.5946},
    {"city": "Kolkata",    "state": "West Bengal",    "lat": 22.5726, "lon": 88.3639},
    {"city": "Chennai",    "state": "Tamil Nadu",     "lat": 13.0827, "lon": 80.2707},
    {"city": "Hyderabad",  "state": "Telangana",      "lat": 17.3850, "lon": 78.4867},
    {"city": "Pune",       "state": "Maharashtra",    "lat": 18.5204, "lon": 73.8567},
    {"city": "Lucknow",    "state": "Uttar Pradesh",  "lat": 26.8467, "lon": 80.9462},
    {"city": "Patna",      "state": "Bihar",          "lat": 25.5941, "lon": 85.1376},
    {"city": "Ahmedabad",  "state": "Gujarat",        "lat": 23.0225, "lon": 72.5714},
    {"city": "Jaipur",     "state": "Rajasthan",      "lat": 26.9124, "lon": 75.7873},
    {"city": "Chandigarh", "state": "Chandigarh",     "lat": 30.7333, "lon": 76.7794},
    {"city": "Bhopal",     "state": "Madhya Pradesh", "lat": 23.2599, "lon": 77.4126},
    {"city": "Kanpur",     "state": "Uttar Pradesh",  "lat": 26.4499, "lon": 80.3319},
    {"city": "Guwahati",   "state": "Assam",          "lat": 26.1445, "lon": 91.7362},
]


def get_aqi_data(city_name, lat, lon, retries=2):
    """Fetch AQI + pollutant data from WAQI. Tries geo-lookup first (more precise),
    then falls back to city-name lookup if the geo station is unreachable."""

    def _try_url(url):
        for attempt in range(1, retries + 1):
            try:
                r = requests.get(url, timeout=10)
                data = r.json()
                if data.get("status") == "ok":
                    d = data["data"]
                    iaqi = d.get("iaqi", {})
                    return {
                        "aqi": d.get("aqi"),
                        "pm25": iaqi.get("pm25", {}).get("v"),
                        "pm10": iaqi.get("pm10", {}).get("v"),
                        "co": iaqi.get("co", {}).get("v"),
                        "no2": iaqi.get("no2", {}).get("v"),
                        "so2": iaqi.get("so2", {}).get("v"),
                        "o3": iaqi.get("o3", {}).get("v"),
                    }
            except Exception:
                pass
            time.sleep(2)
        return None

    # Attempt 1: geo-based (more precise station match)
    geo_url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={WAQI_TOKEN}"
    result = _try_url(geo_url)
    if result:
        return result

    # Attempt 2: fallback to city-name based lookup
    print(f"[WAQI] Geo lookup failed for {city_name}, trying city-name fallback...")
    name_url = f"https://api.waqi.info/feed/{city_name}/?token={WAQI_TOKEN}"
    result = _try_url(name_url)
    if result:
        return result

    print(f"[WAQI] Giving up on {city_name} — station unavailable right now.")
    return None


def get_weather_data(city_name, lat, lon):
    """Fetch temperature, humidity, wind speed from OpenWeatherMap."""
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OWM_API_KEY}&units=metric"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("cod") != 200:
            print(f"[OWM] Failed for {city_name}: {data}")
            return None
        return {
            "temperature": data["main"]["temp"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"],
        }
    except Exception as e:
        print(f"[OWM] Error for {city_name}: {e}")
        return None


def collect_all():
    rows = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for c in CITIES:
        aqi_info = get_aqi_data(c["city"], c["lat"], c["lon"])
        weather_info = get_weather_data(c["city"], c["lat"], c["lon"])

        if aqi_info is None or weather_info is None:
            continue  # skip city if either API failed this round

        row = {
            "timestamp": timestamp,
            "city": c["city"],
            "state": c["state"],
            "lat": c["lat"],
            "lon": c["lon"],
            **aqi_info,
            **weather_info,
        }
        rows.append(row)
        print(f"Collected: {c['city']} -> AQI {aqi_info['aqi']}, Temp {weather_info['temperature']}C")

        time.sleep(1)  # small pause between cities to avoid hammering the APIs

    return rows


def save_to_csv(rows):
    if not rows:
        print("No data collected this run.")
        return

    file_exists = os.path.isfile(CSV_FILE)
    fieldnames = list(rows[0].keys())

    with open(CSV_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {CSV_FILE}")


if __name__ == "__main__":
    print("Starting AQI + Weather data collection...\n")
    collected_rows = collect_all()
    save_to_csv(collected_rows)
    print("\nDone.")
