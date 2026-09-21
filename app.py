import streamlit as st
import os
import re
from agent import run_agent

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

# Reset button, shown in the sidebar
with st.sidebar:
    if st.button("🔄 New Conversation"):
        st.session_state.history = []
        st.session_state.display_messages = []
        st.rerun()


def extract_urgency(text):
    match = re.search(r"\[URGENCY:(LOW|MEDIUM|HIGH)\]", text)
    if match:
        urgency = match.group(1)
        cleaned_text = text.replace(match.group(0), "").strip()
        return urgency,