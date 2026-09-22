import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

RESEARCH_SYSTEM_PROMPT = """You are a poultry disease research assistant. Your job is to search the web for CURRENT, real information relevant to a farmer's question — such as recent disease outbreaks, current weather-related risks, or general poultry health news in their region.

Rules:
- Only report what you actually find from search results — never guess or make up information
- If you find nothing relevant, say so clearly rather than inventing an answer
- Keep answers concise and practical for a farmer, not technical/academic
- Always mention where information came from (e.g. "according to a report from...")
- If asked about anything unrelated to poultry/farming, politely redirect to that topic"""


def run_research_agent(user_question):
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=RESEARCH_SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_question}]
    )

    reply_text = ""
    for block in response.content:
        if block.type == "text":
            reply_text += block.text

    return reply_text


if __name__ == "__main__":
    test_question = "Are there any recent reports of poultry disease outbreaks in Kenya?"
    print(run_research_agent(test_question))