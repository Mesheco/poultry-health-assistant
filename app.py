import streamlit as st
import os
import re
import pandas as pd
from datetime import date, timedelta
from agent import run_agent
from research_agent import run_research_agent
from monitor_agent import run_monitor_agent

APP_NAME = "Mesheco Poultry AI Disease Detector"
LOGO = "logo.png"

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
if "mode" not in st.session_state:
    st.session_state.mode = "Diagnose"
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0   # changing this clears the photo uploader and camera
if "flock_log" not in st.session_state:
    st.session_state.flock_log = []
if "monitor_result" not in st.session_state:
    st.session_state.monitor_result = None

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
        ["Diagnose", "Research", "Monitor"],
        captions=[
            "Describe symptoms for a diagnosis",
            "Check for current outbreak news",
            "Log daily checks and spot early warnings"
        ]
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


def extract_urgency(text):
    match = re.search(r"\[URGENCY:(LOW|MEDIUM|HIGH)\]", text)
    if match:
        urgency = match.group(1)
        cleaned_text = text.replace(match.group(0), "").strip()
        return urgency, cleaned_text
    return None, text


def render_message(role, text, image=None):
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
                st.exception(e)  # TEMPORARY: shows the real error on screen. Remove before the hackathon.
                st.session_state.monitor_result = "Sorry, something went wrong while checking your flock. Please try again in a moment."

    if st.session_state.monitor_result:
        render_message("assistant", st.session_state.monitor_result)


if st.session_state.mode == "Monitor":
    show_monitor_page()
    st.stop()


# ---------------- DIAGNOSE & RESEARCH MODES ----------------

for msg in st.session_state.display_messages:
    render_message(msg["role"], msg["content"], msg.get("image"))

placeholder_text = "Describe your birds' symptoms..." if st.session_state.mode == "Diagnose" else "Ask about current outbreaks or poultry news..."
user_input = st.chat_input(placeholder_text)

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
                    user_input, st.session_state.history, image_bytes=image_bytes
                )
            else:
                reply = run_research_agent(user_input)
        except Exception as e:
            had_error = True
            print("ERROR DETAILS:", repr(e), flush=True)
            st.exception(e)  # TEMPORARY: shows the real error on screen. Remove before the hackathon.
            reply = "Sorry, something went wrong while processing your message. Please try again in a moment."

    render_message("assistant", reply)
    st.session_state.display_messages.append({"role": "assistant", "content": reply})

    # Clear the photo (upload or camera) after a successful send
    if image_bytes and not had_error:
        st.session_state.uploader_key += 1
        st.rerun()