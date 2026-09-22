import streamlit as st
import os
import re
from agent import run_agent
from research_agent import run_research_agent

st.set_page_config(page_title="Poultry Health Assistant", page_icon="🐔")

# Simple password gate — works both locally (.env) and on Streamlit Cloud (Secrets)
try:
    correct_password = os.getenv("APP_PASSWORD") or st.secrets.get("APP_PASSWORD", "")
except Exception:
    correct_password = os.getenv("APP_PASSWORD", "")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Poultry Health Assistant - Login")
    entered_password = st.text_input("Enter password", type="password")
    if st.button("Login"):
        if entered_password == correct_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

st.title("🐔 Poultry Health Assistant")
st.caption("Describe your birds' symptoms and get guidance on likely causes and next steps.")

if "history" not in st.session_state:
    st.session_state.history = []
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []
if "mode" not in st.session_state:
    st.session_state.mode = "Diagnose"

with st.sidebar:
    if st.button("🔄 New Conversation"):
        st.session_state.history = []
        st.session_state.display_messages = []
        st.rerun()

    st.divider()
    st.subheader("Mode")
    st.session_state.mode = st.radio(
        "Choose what you need:",
        ["Diagnose", "Research"],
        captions=[
            "Describe symptoms for a diagnosis",
            "Check for current outbreak news"
        ]
    )


def extract_urgency(text):
    match = re.search(r"\[URGENCY:(LOW|MEDIUM|HIGH)\]", text)
    if match:
        urgency = match.group(1)
        cleaned_text = text.replace(match.group(0), "").strip()
        return urgency, cleaned_text
    return None, text


def render_message(role, text):
    urgency, cleaned_text = extract_urgency(text)

    with st.chat_message(role):
        if urgency == "HIGH":
            st.error("🔴 Urgency: HIGH")
        elif urgency == "MEDIUM":
            st.warning("🟡 Urgency: MEDIUM")
        elif urgency == "LOW":
            st.success("🟢 Urgency: LOW")

        st.markdown(cleaned_text)


for msg in st.session_state.display_messages:
    render_message(msg["role"], msg["content"])

placeholder_text = "Describe your birds' symptoms..." if st.session_state.mode == "Diagnose" else "Ask about current outbreaks or poultry news..."
user_input = st.chat_input(placeholder_text)

if user_input:
    st.session_state.display_messages.append({"role": "user", "content": user_input})
    render_message("user", user_input)

    with st.spinner("Thinking..."):
        try:
            if st.session_state.mode == "Diagnose":
                reply, st.session_state.history = run_agent(user_input, st.session_state.history)
            else:
                reply = run_research_agent(user_input)
        except Exception as e:
            print("ERROR DETAILS:", repr(e), flush=True)
            st.exception(e)  # TEMPORARY: shows the real error on screen. Remove before the hackathon.
            reply = "Sorry, something went wrong while processing your message. Please try again in a moment."

    render_message("assistant", reply)
    st.session_state.display_messages.append({"role": "assistant", "content": reply})
