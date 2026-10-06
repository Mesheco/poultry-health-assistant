"""
Nearby help: finds agrovets, vets and boda boda delivery riders close to the farmer.

Two sources, always kept apart so the farmer knows what to trust:
  1. VERIFIED contacts from vet_contacts.json (checked by the Mesheco team)
  2. MAP listings from OpenStreetMap (free, no API key) - shown as "unverified, call first"

This file does not use Streamlit, so the Diagnose agent can call it as a tool too.
"""

import json
import math
import re
import time
from urllib.parse import quote

import requests

CONTACTS_FILE = "vet_contacts.json"
USER_AGENT = "MeshecoPoultryAI/1.0 (hackathon project; github.com/Mesheco/poultry-health-assistant)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",   # backup server if the first is busy
]
CACHE_SECONDS = 60 * 60   # remember map results for an hour, so we don't overload the free servers

_cache = {}


def _cached(key, fetch):
    """Return a saved result if we fetched it recently, otherwise fetch and save it."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fetch()
    _cache[key] = (time.time(), value)
    return value


# ---------------- distance and links ----------------

def distance_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two points on Earth (haversine formula)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def to_international(phone):
    """'0717 138 312' -> '254717138312'. Returns '' if it doesn't look like a phone number."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("254"):
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if len(digits) == 9 and digits[0] in "71":
        return "254" + digits
    return ""


def call_link(phone):
    intl = to_international(phone)
    return f"tel:+{intl}" if intl else ""


def whatsapp_link(phone, message):
    """Open a WhatsApp chat with this number. Only Kenyan mobile numbers (07.. or 01..) use WhatsApp."""
    intl = to_international(phone)
    if not intl or intl[3] not in "71":
        return ""
    return f"https://wa.me/{intl}?text={quote(message)}"


def directions_link(to_lat, to_lon, from_lat=None, from_lon=None):
    link = f"https://www.google.com/maps/dir/?api=1&destination={to_lat},{to_lon}"
    if from_lat is not None and from_lon is not None:
        link += f"&origin={from_lat},{from_lon}"
    return link


def map_pin_link(lat, lon):
    return f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"


def delivery_message(farmer_lat, farmer_lon, items=""):
    """The WhatsApp message a farmer sends to ask for delivery by boda boda."""
    what = items.strip() or "some supplies for my chickens"
    return (
        "Hello, I found you on Mesheco Poultry AI.\n"
        f"I need: {what}.\n"
        "Can you deliver by boda boda to my farm? Please tell me the price and delivery cost.\n"
        f"My location: {map_pin_link(farmer_lat, farmer_lon)}"
    )


# ---------------- finding places on the map ----------------

def geocode_place(place_text):
    """Turn a typed place like 'Gatundu' into coordinates. Returns dict or None."""
    place_text = (place_text or "").strip()
    if not place_text:
        return None

    def fetch():
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place_text, "format": "json", "countrycodes": "ke", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        top = results[0]
        return {
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
            "label": top.get("display_name", place_text).split(",")[0],
        }

    return _cached(("geo", place_text.lower()), fetch)


def _classify(tags):
    """Decide whether a map listing is a vet or an agrovet."""
    name = (tags.get("name") or "").lower()
    if tags.get("amenity") == "veterinary" or "vet clinic" in name or "veterinary" in name:
        return "Vet clinic"
    return "Agrovet"


def find_map_places(lat, lon, radius_km=15):
    """Search OpenStreetMap for agrovets, farm shops and vet clinics near a point."""
    radius_m = int(radius_km * 1000)
    around = f"(around:{radius_m},{lat},{lon})"
    query = f"""
    [out:json][timeout:25];
    (
      nwr["shop"~"^(agrarian|farm|feed)$"]{around};
      nwr["amenity"="veterinary"]{around};
      nwr["name"~"agro.?vet|agrovet|veterinary|farmers? (shop|centre|center)",i]{around};
    );
    out center tags 80;
    """

    def fetch():
        last_error = None
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query},
                                     headers={"User-Agent": USER_AGENT}, timeout=30)
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except Exception as e:   # try the backup server
                last_error = e
        raise last_error

    elements = _cached(("osm", round(lat, 3), round(lon, 3), radius_km), fetch)

    places = []
    seen = set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        p_lat = el.get("lat") or el.get("center", {}).get("lat")
        p_lon = el.get("lon") or el.get("center", {}).get("lon")
        if not name or p_lat is None or p_lon is None:
            continue
        key = (name.lower(), round(p_lat, 3), round(p_lon, 3))
        if key in seen:
            continue
        seen.add(key)
        places.append({
            "name": name,
            "type": _classify(tags),
            "location": tags.get("addr:street") or tags.get("addr:city") or tags.get("addr:place") or "",
            "phone": tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile") or "",
            "lat": float(p_lat),
            "lon": float(p_lon),
            "delivery": False,
            "verified": False,
            "source": "Map listing (OpenStreetMap)",
        })
    return places


# ---------------- verified directory ----------------

def load_directory():
    try:
        with open(CONTACTS_FILE, encoding="utf-8") as f:
            return json.load(f).get("contacts", [])
    except Exception:
        return []


def _directory_with_coords():
    """Verified contacts with coordinates. If a contact has no lat/lon, look up its location text."""
    out = []
    for c in load_directory():
        lat, lon, approx = c.get("lat"), c.get("lon"), False
        if lat is None or lon is None:
            try:
                found = geocode_place(c.get("location", ""))
            except Exception:
                found = None
            if not found:
                continue
            lat, lon, approx = found["lat"], found["lon"], True
        out.append({
            "name": c["name"],
            "type": c.get("type", ""),
            "location": c.get("location", ""),
            "phone": c.get("phone", ""),
            "lat": float(lat),
            "lon": float(lon),
            "delivery": bool(c.get("delivery", False)) or c.get("type", "").lower().startswith("boda"),
            "verified": True,
            "approx_location": approx,
            "source": "Verified by Mesheco",
        })
    return out


# ---------------- the main function ----------------

def find_nearby_help(lat, lon, radius_km=15, include_map=True):
    """
    Everything near the farmer, nearest first.
    Returns {"places": [...], "map_error": str or None}.
    Verified contacts are always included even if slightly outside the radius,
    because a known vet 25 km away beats nobody.
    """
    places = []
    for p in _directory_with_coords():
        p["distance_km"] = round(distance_km(lat, lon, p["lat"], p["lon"]), 1)
        if p["distance_km"] <= max(radius_km, 50):
            places.append(p)

    map_error = None
    if include_map:
        try:
            for p in find_map_places(lat, lon, radius_km):
                p["distance_km"] = round(distance_km(lat, lon, p["lat"], p["lon"]), 1)
                places.append(p)
        except Exception as e:
            map_error = f"The map search is busy or unreachable right now ({type(e).__name__}). Showing verified contacts only."

    # Verified first when distances are similar; otherwise nearest first
    places.sort(key=lambda p: (p["distance_km"] - (2 if p["verified"] else 0)))
    return {"places": places, "map_error": map_error}


def summarise_for_agent(lat, lon, radius_km=15, limit=5):
    """A short, safe summary the Diagnose agent can read (used as a tool result)."""
    result = find_nearby_help(lat, lon, radius_km)
    rows = []
    for p in result["places"][:limit]:
        rows.append({
            "name": p["name"],
            "type": p["type"],
            "distance_km": p["distance_km"],
            "verified": p["verified"],
            "has_phone": bool(p["phone"]),
            "offers_delivery": p["delivery"],
        })
    return {
        "places": rows,
        "note": ("Verified places were checked by Mesheco. Unverified places come from a public map "
                 "and the farmer should call or visit to confirm first. Phone numbers and map links "
                 "are shown to the farmer in the app, so do not write them out."),
        "map_error": result["map_error"],
    }
