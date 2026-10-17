"""Distance/ETA estimate. Uses Google Maps Distance Matrix when a key is set,
otherwise a seeded city table. The result always states which source was used."""
import os
import json
import urllib.parse
import urllib.request

WAREHOUSE_ADDRESS = {"WH-EAST": "Newark, NJ, USA", "WH-WEST": "Oakland, CA, USA"}

# Approximate road km from each hub. Used only when Maps is unavailable.
SIMULATED_KM = {
    "WH-EAST": {"New York": 15, "Boston": 350, "Chicago": 1270, "Atlanta": 1150, "Miami": 2000,
                "Dallas": 2450, "Denver": 2900, "Austin": 2900, "Seattle": 4700,
                "San Francisco": 4900, "Oakland": 4900, "Los Angeles": 4500},
    "WH-WEST": {"San Francisco": 15, "Oakland": 5, "Los Angeles": 600, "Seattle": 1300,
                "Denver": 1900, "Dallas": 2400, "Austin": 2800, "Chicago": 3400,
                "Atlanta": 3800, "Boston": 4900, "New York": 4900, "Miami": 4800},
}


def _eta_days(km: float) -> int:
    return 1 if km < 1500 else 2 if km < 3500 else 3


def estimate_route(warehouse_id: str, destination_city: str) -> dict:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    origin = WAREHOUSE_ADDRESS.get(warehouse_id, "Newark, NJ, USA")
    if key:
        try:
            qs = urllib.parse.urlencode({
                "origins": origin, "destinations": f"{destination_city}, USA",
                "units": "metric", "key": key,
            })
            with urllib.request.urlopen(
                f"https://maps.googleapis.com/maps/api/distancematrix/json?{qs}", timeout=6
            ) as resp:
                data = json.loads(resp.read())
            el = data["rows"][0]["elements"][0]
            if el.get("status") == "OK":
                km = el["distance"]["value"] / 1000
                return {"source": "google_maps", "simulated": False, "origin": origin,
                        "destination": destination_city, "distance_km": round(km, 1),
                        "duration_hours": round(el["duration"]["value"] / 3600, 1),
                        "eta_days": _eta_days(km)}
            reason = f"Maps element status {el.get('status')}: {data.get('error_message', '')}"
        except Exception as exc:  # network, quota, bad key
            reason = f"Maps call failed: {exc}"
    else:
        reason = "GOOGLE_MAPS_API_KEY not set"
    km = SIMULATED_KM.get(warehouse_id, {}).get(destination_city, 1500)
    return {"source": "simulated_table", "simulated": True, "fallback_reason": reason,
            "origin": origin, "destination": destination_city, "distance_km": km,
            "duration_hours": round(km / 80, 1), "eta_days": _eta_days(km)}
