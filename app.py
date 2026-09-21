import streamlit as st
import re
from agent import run_agent

st.set_page_config(page_title="Poultry Health Assistant", page_icon="🐔")

st.title("🐔 Poultry Health Assistant")
st.caption("Describe your birds' symptoms and get guidance on likely causes and next steps.")

if "history" not in st.session_state:
    st.session_state.history = []
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []


def extract_urgency(text):
    """
    Looks for a tag like [URGENCY:HIGH] in the text.
    Returns (urgency_level, cleaned_text) — cleaned_text has the tag removed.
    """
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


# Show all previous messages in the conversation
for msg in st.session_state.display_messages:
    render_message(msg["role"], msg["content"])

# Input box at the bottom, like a real chat app
user_input = st.chat_input("Describe your birds' symptoms...")

if user_input:
    st.session_state.display_messages.append({"role": "user", "content": user_input})
    render_message("user", user_input)

    with st.spinner("Thinking..."):
        reply, st.session_state.history = run_agent(user_input, st.session_state.history)

    render_message("assistant", reply)
    st.session_state.display_messages.append({"role": "assistant", "content": reply})