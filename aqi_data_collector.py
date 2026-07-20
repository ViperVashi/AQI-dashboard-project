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
    # ---- Already-covered major cities (kept as-is) ----
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

    # ---- Remaining state capitals ----
    {"city": "Amaravati",         "state": "Andhra Pradesh",     "lat": 16.5130, "lon": 80.5165},
    {"city": "Itanagar",          "state": "Arunachal Pradesh",  "lat": 27.0844, "lon": 93.6053},
    {"city": "Dispur",            "state": "Assam",              "lat": 26.1433, "lon": 91.7898},
    {"city": "Raipur",            "state": "Chhattisgarh",       "lat": 21.2514, "lon": 81.6296},
    {"city": "Panaji",            "state": "Goa",                "lat": 15.4909, "lon": 73.8278},
    {"city": "Gandhinagar",       "state": "Gujarat",            "lat": 23.2156, "lon": 72.6369},
    {"city": "Shimla",            "state": "Himachal Pradesh",   "lat": 31.1048, "lon": 77.1734},
    {"city": "Ranchi",            "state": "Jharkhand",          "lat": 23.3441, "lon": 85.3096},
    {"city": "Thiruvananthapuram","state": "Kerala",             "lat": 8.5241,  "lon": 76.9366},
    {"city": "Imphal",            "state": "Manipur",            "lat": 24.8170, "lon": 93.9368},
    {"city": "Shillong",          "state": "Meghalaya",          "lat": 25.5788, "lon": 91.8933},
    {"city": "Aizawl",            "state": "Mizoram",            "lat": 23.7271, "lon": 92.7176},
    {"city": "Kohima",            "state": "Nagaland",           "lat": 25.6751, "lon": 94.1086},
    {"city": "Bhubaneswar",       "state": "Odisha",             "lat": 20.2961, "lon": 85.8245},
    {"city": "Gangtok",           "state": "Sikkim",             "lat": 27.3389, "lon": 88.6065},
    {"city": "Agartala",          "state": "Tripura",            "lat": 23.8315, "lon": 91.2868},
    {"city": "Dehradun",          "state": "Uttarakhand",        "lat": 30.3165, "lon": 78.0322},

    # ---- Remaining Union Territories ----
    {"city": "Port Blair",  "state": "Andaman and Nicobar Islands",              "lat": 11.6234, "lon": 92.7265},
    {"city": "Daman",       "state": "Dadra and Nagar Haveli and Daman and Diu", "lat": 20.3974, "lon": 72.8328},
    {"city": "Srinagar",    "state": "Jammu and Kashmir",                        "lat": 34.0837, "lon": 74.7973},
    {"city": "Leh",         "state": "Ladakh",                                   "lat": 34.1526, "lon": 77.5771},
    {"city": "Kavaratti",   "state": "Lakshadweep",                              "lat": 10.5669, "lon": 72.6420},
    {"city": "Puducherry",  "state": "Puducherry",                               "lat": 11.9416, "lon": 79.8083},
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
