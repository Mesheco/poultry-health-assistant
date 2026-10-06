import streamlit as st
import os
import re
import json
import pandas as pd
from datetime import date, timedelta
from urllib.parse import quote
from agent import run_agent
from research_agent import run_research_agent
from monitor_agent import run_monitor_agent, calculate_key_facts
from streamlit_js_eval import get_geolocation
from nearby_help import (find_nearby_help, geocode_place, call_link,
                         whatsapp_link as whatsapp_chat_link,
                         directions_link, delivery_message)

APP_NAME = "Mesheco Poultry AI Disease Detector"
LOGO = "logo.png"
FIND_HELP = "Find help near you"

st.set_page_config(page_title=APP_NAME, page_icon=LOGO)
st.logo(LOGO)

# Simple password gate — works both locally (.env) and on Streamlit Cloud (Secrets)
try:
    correct_password = os.getenv("APP_PASSWORD") or st.secrets.get("APP_PASSWORD", "")
except Exception:
    correct_password = os.getenv("APP_PASSWORD", "")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.image(LOGO, width=120)
    st.title(APP_NAME)
    st.caption("🔒 Please log in to continue")
    entered_password = st.text_input("Enter password", type="password")
    if st.button("Login"):
        if entered_password == correct_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

logo_col, title_col = st.columns([1, 6], vertical_alignment="center")
with logo_col:
    st.image(LOGO, width=80)
with title_col:
    st.title(APP_NAME)
st.caption("Describe your birds' symptoms and get guidance on likely causes and next steps.")

LOG_COLUMNS = ["date", "total_birds", "deaths", "eggs", "feed_kg", "water_litres", "symptoms"]
NUMBER_COLUMNS = ["total_birds", "deaths", "eggs", "feed_kg", "water_litres"]

if "history" not in st.session_state:
    st.session_state.history = []
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0   # changing this clears the photo uploader and camera
if "flock_log" not in st.session_state:
    st.session_state.flock_log = []
if "monitor_result" not in st.session_state:
    st.session_state.monitor_result = None
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None   # a message waiting to be sent to Diagnose (from Monitor)
if "location" not in st.session_state:
    st.session_state.location = None         # {"lat", "lon", "label"} once the farmer shares it
if "gps_request" not in st.session_state:
    st.session_state.gps_request = 0         # counts "use my location" clicks (0 = not asked)
if "delivery_items" not in st.session_state:
    st.session_state.delivery_items = ""


def apply_link_from_agrinexus():
    """
    AgriNexus (and any other app) can open Mesheco on the right page with a link like:
      ...streamlit.app/?mode=diagnose&q=my birds are sneezing&lat=-1.01&lon=36.90&from=agrinexus
    mode: diagnose | research | monitor | find-help
    q:    a question to send to the Diagnose agent straight away
    lat/lon: the farmer's location, so Find help and the Diagnose agent know where they are
    This runs once per visit.
    """
    if st.session_state.get("link_applied"):
        return
    st.session_state.link_applied = True
    params = st.query_params
    modes = {"diagnose": "Diagnose", "research": "Research", "monitor": "Monitor",
             "find-help": FIND_HELP, "findhelp": FIND_HELP, "nearby": FIND_HELP}
    mode = modes.get(params.get("mode", "").lower())
    if mode:
        st.session_state.mode_radio = mode
    try:
        lat, lon = float(params["lat"]), float(params["lon"])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            source = "AgriNexus" if params.get("from", "").lower() == "agrinexus" else "your link"
            st.session_state.location = {"lat": lat, "lon": lon, "label": f"Location shared from {source}"}
    except (KeyError, ValueError):
        pass
    question = params.get("q", "").strip()[:1000]
    if question and mode in (None, "Diagnose"):
        st.session_state.mode_radio = "Diagnose"
        st.session_state.pending_prompt = question


apply_link_from_agrinexus()


def go_to_find_help():
    """Switch the sidebar to the Find help page."""
    st.session_state.mode_radio = FIND_HELP


def start_diagnosis_from_log(message):
    """Called when the farmer clicks the handoff button in Monitor mode."""
    st.session_state.mode_radio = "Diagnose"      # switch the sidebar to Diagnose
    st.session_state.pending_prompt = message     # send this message automatically
    st.session_state.history = []                 # start a fresh diagnosis conversation
    st.session_state.display_messages = []


uploaded_photo = None

with st.sidebar:
    if st.button("🔄 New Conversation"):
        st.session_state.history = []
        st.session_state.display_messages = []
        st.session_state.uploader_key += 1
        st.rerun()

    st.divider()
    st.subheader("Mode")
    st.session_state.mode = st.radio(
        "Choose what you need:",
        ["Diagnose", "Research", "Monitor", FIND_HELP],
        captions=[
            "Describe symptoms for a diagnosis",
            "Check for current outbreak news",
            "Log daily checks and spot early warnings",
            "Agrovets, vets and boda delivery near you"
        ],
        key="mode_radio"
    )

    # Photo — only in Diagnose mode: upload an existing photo OR take one with the camera
    if st.session_state.mode == "Diagnose":
        st.divider()
        st.subheader("📷 Add a photo (optional)")
        photo_method = st.radio(
            "How would you like to add a photo?",
            ["Upload a photo", "Take a photo"],
            horizontal=True,
            key="photo_method"
        )

        if photo_method == "Upload a photo":
            uploaded_photo = st.file_uploader(
                "Photo of droppings, a sick bird, or a lesion",
                type=["jpg", "jpeg", "png", "webp"],
                key=f"photo_{st.session_state.uploader_key}"
            )
            if uploaded_photo is not None:
                st.image(uploaded_photo, caption="Will be sent with your next message")
        else:
            uploaded_photo = st.camera_input(
                "Point the camera at the bird or droppings, then click Take Photo",
                key=f"camera_{st.session_state.uploader_key}"
            )
            if uploaded_photo is not None:
                st.caption("✅ Photo ready. It will be sent with your next message.")

    # Location status — shown in every mode
    st.divider()
    if st.session_state.location:
        st.caption(f"📍 Your location: **{st.session_state.location['label']}**")
    else:
        st.caption("📍 Location not shared yet. Share it to see agrovets, vets and boda riders near you.")
        if st.session_state.mode != FIND_HELP:
            st.button("📍 Find help near me", on_click=go_to_find_help, key="sidebar_find_help")


def extract_urgency(text):
    match = re.search(r"\[URGENCY:(LOW|MEDIUM|HIGH)\]", text)
    if match:
        urgency = match.group(1)
        cleaned_text = text.replace(match.group(0), "").strip()
        return urgency, cleaned_text
    return None, text


def to_whatsapp_format(text):
    """Convert the app's Markdown into WhatsApp's simpler formatting."""
    text = re.sub(r"^\s*-{3,}\s*$", "", text, flags=re.M)           # remove --- divider lines
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)           # bullet points -> •
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)                  # **bold** -> *bold*
    text = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", text, flags=re.M)    # ## Heading -> *Heading*
    text = re.sub(r"\*{2,}", "*", text)                             # tidy any leftover stars
    text = re.sub(r"\n{3,}", "\n\n", text)                          # remove extra blank lines
    return text


def whatsapp_link(text):
    """Build a link that opens WhatsApp with the reply ready to send."""
    urgency, cleaned_text = extract_urgency(text)
    header = "Mesheco Poultry AI"
    if urgency:
        header += f" (Urgency: {urgency})"
    body = f"*{header}*\n\n{to_whatsapp_format(cleaned_text)}"
    if len(body) > 1800:   # keep the link a safe length for WhatsApp
        body = body[:1800] + "…"
    return "https://wa.me/?text=" + quote(body)


# ---------------- NEARBY HELP ----------------

def cached_nearby(lat, lon, radius_km):
    # nearby_help.py remembers successful map searches for an hour, but not failures,
    # so a busy map server is retried on the next visit.
    return find_nearby_help(lat, lon, radius_km)


def cached_geocode(place_text):
    return geocode_place(place_text)


def render_place(p, farmer):
    """One card for a vet, agrovet or boda rider, with call / WhatsApp / directions / delivery buttons."""
    badge = "✅ Verified" if p["verified"] else "🗺️ Map listing · call to confirm"
    about = " · ".join(x for x in [p["type"], p.get("location", "")] if x)
    dist = "less than 1 km away" if p["distance_km"] < 1 else f"about {p['distance_km']} km away"
    if p.get("approx_location"):
        dist += " (approximate)"

    links = []
    if p["phone"] and call_link(p["phone"]):
        links.append(f"[📞 Call {p['phone']}]({call_link(p['phone'])})")
    chat = whatsapp_chat_link(p["phone"], "Hello, I found you on Mesheco Poultry AI. I need help with my chickens.")
    if chat:
        links.append(f"[💬 WhatsApp]({chat})")
    links.append(f"[🧭 Directions]({directions_link(p['lat'], p['lon'], farmer['lat'], farmer['lon'])})")
    delivery = whatsapp_chat_link(p["phone"], delivery_message(farmer["lat"], farmer["lon"],
                                                          st.session_state.delivery_items))
    if delivery and (p["delivery"] or "agro" in p["type"].lower()):
        label = "🛵 Book boda delivery" if p["type"].lower().startswith("boda") else "🛵 Ask for boda delivery"
        links.append(f"[{label}]({delivery})")

    with st.container(border=True):
        st.markdown(f"**{p['name']}**  \n{badge}  \n{about} · {dist}")
        st.markdown(" · ".join(links))
        if not p["phone"]:
            st.caption("No phone number listed. Use directions to visit.")


def render_nearest_help(key):
    """Shown under MEDIUM/HIGH replies: the nearest few places, or a button to share location."""
    loc = st.session_state.location
    if not loc:
        st.info("📞 Need a vet or agrovet? Share your location to see the nearest ones.")
        st.button("📍 Find help near me", on_click=go_to_find_help, key=f"find_help_{key}")
        return
    result = cached_nearby(loc["lat"], loc["lon"], 15)
    places = [p for p in result["places"] if not p["type"].lower().startswith("boda")][:3]
    if not places:
        st.info("No vets or agrovets found within 15 km. Open **Find help near you** to search wider, "
                "or contact your county veterinary office.")
        return
    st.markdown("**📞 Nearest help to you**")
    for p in places:
        render_place(p, loc)


def render_message(role, text, image=None, share=False, key="new"):
    urgency, cleaned_text = extract_urgency(text)

    with st.chat_message(role):
        if image:
            st.image(image, width=250)

        if urgency == "HIGH":
            st.error("🔴 Urgency: HIGH")
        elif urgency == "MEDIUM":
            st.warning("🟡 Urgency: MEDIUM")
        elif urgency == "LOW":
            st.success("🟢 Urgency: LOW")

        st.markdown(cleaned_text)

        if role == "assistant" and urgency in ("MEDIUM", "HIGH"):
            render_nearest_help(key)

        if share:
            st.markdown(f"[📤 Share on WhatsApp]({whatsapp_link(text)})")


# ---------------- MONITOR MODE ----------------

def sample_log():
    """A made-up week where illness slowly builds up — useful for demos."""
    today = date.today()
    deaths = [0, 0, 1, 1, 3, 5, 8]
    eggs = [150, 148, 149, 140, 128, 115, 100]
    feed = [22.0, 22.0, 21.5, 20.0, 18.0, 16.0, 14.0]
    water = [40.0, 41.0, 40.0, 38.0, 34.0, 30.0, 27.0]
    notes = ["", "", "", "a few birds quiet", "some watery droppings",
             "ruffled feathers, some sneezing", "many birds weak and sleepy"]
    rows = []
    birds = 200
    for i in range(7):
        rows.append({
            "date": (today - timedelta(days=6 - i)).isoformat(),
            "total_birds": birds,
            "deaths": deaths[i],
            "eggs": eggs[i],
            "feed_kg": feed[i],
            "water_litres": water[i],
            "symptoms": notes[i],
        })
        birds -= deaths[i]
    return rows


def build_handoff_message(df):
    """Turn the flock log into a message for the Diagnose agent."""
    facts = calculate_key_facts(df.to_csv(index=False))
    notes = [f"{r['date']}: {r['symptoms']}" for r in st.session_state.flock_log
             if str(r.get("symptoms", "")).strip()]
    notes_text = "\n".join("- " + n for n in notes) if notes else "- No symptoms were written in the log"
    return (
        "My flock monitoring log is showing warning signs. Please help me work out what might be wrong.\n\n"
        f"Key facts from my log:\n{facts}\n\n"
        f"Symptoms I noted:\n{notes_text}"
    )


def show_monitor_page():
    st.subheader("📋 Daily Flock Log")
    st.caption("Record a quick check each day. The Monitor agent looks for early warning signs across days.")

    # Load a saved log or sample data
    with st.expander("📂 Load a saved log or sample data"):
        saved_file = st.file_uploader("Upload a log you downloaded earlier (CSV)", type=["csv"], key="log_upload")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Load uploaded log", disabled=saved_file is None):
                try:
                    df_loaded = pd.read_csv(saved_file).fillna("")
                    missing = [c for c in LOG_COLUMNS if c not in df_loaded.columns]
                    if missing:
                        st.error("This file is missing columns: " + ", ".join(missing))
                    else:
                        st.session_state.flock_log = df_loaded[LOG_COLUMNS].to_dict("records")
                        st.session_state.monitor_result = None
                        st.rerun()
                except Exception as e:
                    st.error(f"Could not read this file: {e}")
        with col2:
            if st.button("Load sample data (for demo)"):
                st.session_state.flock_log = sample_log()
                st.session_state.monitor_result = None
                st.rerun()

    # Daily entry form
    with st.form("daily_entry", clear_on_submit=True):
        st.markdown("**Add a daily check**")
        c1, c2, c3 = st.columns(3)
        entry_date = c1.date_input("Date", value=date.today())
        total_birds = c2.number_input("Birds in flock", min_value=0, step=1, value=0)
        deaths = c3.number_input("Deaths today", min_value=0, step=1, value=0)
        c4, c5, c6 = st.columns(3)
        eggs = c4.number_input("Eggs collected", min_value=0, step=1, value=0)
        feed = c5.number_input("Feed used (kg)", min_value=0.0, step=0.5, value=0.0)
        water = c6.number_input("Water used (litres)", min_value=0.0, step=0.5, value=0.0)
        symptoms = st.text_input("Anything unusual? (optional)",
                                 placeholder="e.g. some birds sneezing, watery droppings")
        submitted = st.form_submit_button("➕ Add entry")

    if submitted:
        if total_birds == 0:
            st.warning("Please enter the number of birds in the flock.")
        else:
            new_row = {
                "date": entry_date.isoformat(),
                "total_birds": int(total_birds),
                "deaths": int(deaths),
                "eggs": int(eggs),
                "feed_kg": float(feed),
                "water_litres": float(water),
                "symptoms": symptoms.strip(),
            }
            # Replace an existing entry for the same date, then keep the log in date order
            log = [r for r in st.session_state.flock_log if str(r["date"]) != new_row["date"]]
            log.append(new_row)
            log.sort(key=lambda r: str(r["date"]))
            st.session_state.flock_log = log
            st.session_state.monitor_result = None
            st.success(f"Entry for {new_row['date']} saved.")

    if not st.session_state.flock_log:
        st.info("No entries yet. Add a daily check above, or load sample data to try it out.")
        return

    # Table
    df = pd.DataFrame(st.session_state.flock_log, columns=LOG_COLUMNS)
    st.dataframe(df, hide_index=True)

    # Charts
    chart_df = df.set_index("date")
    for col in NUMBER_COLUMNS:
        chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce")
    tab1, tab2, tab3 = st.tabs(["Deaths", "Feed & water", "Eggs"])
    with tab1:
        st.bar_chart(chart_df[["deaths"]])
    with tab2:
        st.line_chart(chart_df[["feed_kg", "water_litres"]])
    with tab3:
        st.line_chart(chart_df[["eggs"]])

    # Save / remove
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("💾 Download log (CSV)", df.to_csv(index=False),
                           file_name="flock_log.csv", mime="text/csv")
    with c2:
        if st.button("🗑️ Remove last entry"):
            st.session_state.flock_log.pop()
            st.session_state.monitor_result = None
            st.rerun()

    # Ask the Monitor agent
    st.divider()
    if st.button("🔍 Check my flock", type="primary"):
        with st.spinner("Checking your flock records..."):
            try:
                st.session_state.monitor_result = run_monitor_agent(df.to_csv(index=False))
            except Exception as e:
                print("ERROR DETAILS:", repr(e), flush=True)
                st.session_state.monitor_result = "Sorry, something went wrong while checking your flock. Please try again in a moment."

    if st.session_state.monitor_result:
        render_message("assistant", st.session_state.monitor_result, share=True)

        # Handoff: if the Monitor found warning signs, offer a one-click diagnosis
        urgency, _ = extract_urgency(st.session_state.monitor_result)
        if urgency in ("MEDIUM", "HIGH"):
            st.info("The Monitor found warning signs. The Diagnose agent can help work out possible causes.")
            st.button(
                "🩺 Get a diagnosis for these warning signs",
                type="primary",
                on_click=start_diagnosis_from_log,
                args=(build_handoff_message(df),)
            )


if st.session_state.mode == "Monitor":
    show_monitor_page()
    st.stop()


# ---------------- FIND HELP MODE ----------------

def show_find_help_page():
    st.subheader("📍 Find help near you")
    st.caption("Agrovets, vets and boda boda riders near your farm, nearest first.")

    # 1. Get the farmer's location: GPS from the phone, or a typed town
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    with c1:
        if st.button("📍 Use my current location", type="primary"):
            st.session_state.gps_request += 1
    with c2:
        with st.form("place_search", clear_on_submit=False, border=False):
            fc1, fc2 = st.columns([3, 1], vertical_alignment="bottom")
            typed = fc1.text_input("Or type your town or village", placeholder="e.g. Gatundu, Thika, Kitengela")
            searched = fc2.form_submit_button("Search")
    if searched and typed.strip():
        with st.spinner("Finding that place..."):
            try:
                found = cached_geocode(typed.strip())
            except Exception:
                found = False
                st.error("Could not reach the map service. Please try again in a moment.")
        if found:
            st.session_state.location = found
            st.session_state.gps_request = 0
        elif found is None:
            st.warning("We couldn't find that place. Try a nearby town or add the county, e.g. 'Gatundu, Kiambu'.")

    if st.session_state.gps_request:
        geo = get_geolocation(component_key=f"gps_{st.session_state.gps_request}")
        if geo is None:
            st.caption("⏳ Waiting for your phone or browser. If it asks, tap **Allow** to share your location.")
        elif "error" in geo:
            st.session_state.gps_request = 0
            st.warning("Location was blocked or not available. You can type your town instead.")
        else:
            coords = geo["coords"]
            st.session_state.location = {
                "lat": coords["latitude"],
                "lon": coords["longitude"],
                "label": f"Your current location (within about {int(coords.get('accuracy') or 0)} m)",
            }
            st.session_state.gps_request = 0
            st.rerun()

    loc = st.session_state.location
    if not loc:
        st.info("Share your location or type your town to see help near you.")
        return
    st.success(f"Showing help near: **{loc['label']}**")

    # 2. Options
    o1, o2 = st.columns(2)
    radius = o1.select_slider("Search distance (km)", options=[5, 10, 15, 25, 40], value=15)
    show = o2.radio("Show", ["Everything", "Agrovets & vets", "Boda delivery"], horizontal=True)
    st.session_state.delivery_items = st.text_input(
        "What do you need delivered? (optional, added to delivery messages)",
        value=st.session_state.delivery_items,
        placeholder="e.g. 1 bag of layers mash, vitamins, a drinker",
    )

    # 3. Search
    with st.spinner("Looking for help near you..."):
        result = cached_nearby(loc["lat"], loc["lon"], radius)
    if result["map_error"]:
        st.warning(result["map_error"])

    places = result["places"]
    if show == "Agrovets & vets":
        places = [p for p in places if not p["type"].lower().startswith("boda")]
    elif show == "Boda delivery":
        places = [p for p in places if p["delivery"]]

    if not places:
        if show == "Boda delivery":
            st.info("No verified boda riders listed here yet. Tap **🛵 Ask for boda delivery** on an "
                    "agrovet card: many agrovets can send supplies with a boda rider they trust.")
        else:
            st.info("Nothing found within this distance. Try a bigger search distance, "
                    "or contact your county veterinary office.")
        return

    # 4. Map: you (green) and the places (orange = verified, blue = map listing)
    map_rows = [{"lat": loc["lat"], "lon": loc["lon"], "color": "#2e7d32", "size": 120}]
    for p in places:
        map_rows.append({"lat": p["lat"], "lon": p["lon"],
                         "color": "#ef6c00" if p["verified"] else "#1e88e5", "size": 80})
    st.map(pd.DataFrame(map_rows), latitude="lat", longitude="lon", color="color", size="size")
    st.caption("🟢 You · 🟠 Verified by Mesheco · 🔵 Map listing (OpenStreetMap, may be out of date)")

    # 5. Cards
    st.markdown(f"**{len(places)} found, nearest first**")
    for p in places[:20]:
        render_place(p, loc)
    st.caption("Distances are straight-line, so the road trip may be longer. "
               "Always confirm prices and stock before a boda rider sets off.")


if st.session_state.mode == FIND_HELP:
    show_find_help_page()
    st.stop()


# ---------------- DIAGNOSE & RESEARCH MODES ----------------

for i, msg in enumerate(st.session_state.display_messages):
    is_shareable = msg["role"] == "assistant" and not msg.get("error")
    render_message(msg["role"], msg["content"], msg.get("image"), share=is_shareable, key=i)

placeholder_text = "Describe your birds' symptoms..." if st.session_state.mode == "Diagnose" else "Ask about current outbreaks or poultry news..."
user_input = st.chat_input(placeholder_text)

# A message handed over from the Monitor agent is sent automatically
if not user_input and st.session_state.mode == "Diagnose" and st.session_state.pending_prompt:
    user_input = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

if user_input:
    image_bytes = None
    if st.session_state.mode == "Diagnose" and uploaded_photo is not None:
        image_bytes = uploaded_photo.getvalue()

    st.session_state.display_messages.append({"role": "user", "content": user_input, "image": image_bytes})
    render_message("user", user_input, image_bytes)

    had_error = False
    with st.spinner("Thinking..."):
        try:
            if st.session_state.mode == "Diagnose":
                reply, st.session_state.history = run_agent(
                    user_input, st.session_state.history, image_bytes=image_bytes,
                    location=st.session_state.location
                )
            else:
                reply = run_research_agent(user_input)
        except Exception as e:
            had_error = True
            print("ERROR DETAILS:", repr(e), flush=True)
            reply = "Sorry, something went wrong while processing your message. Please try again in a moment."

    render_message("assistant", reply, share=not had_error)
    st.session_state.display_messages.append({"role": "assistant", "content": reply, "error": had_error})

    # Clear the photo (upload or camera) after a successful send
    if image_bytes and not had_error:
        st.session_state.uploader_key += 1
        st.rerun()