import os
from datetime import date
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-5"
MAX_SEARCHES = 5          # limits how many web searches one question can use (keeps costs down)
MAX_CONTINUATIONS = 3     # long searches can pause; this lets them finish

RESEARCH_SYSTEM_PROMPT = """You are the Research agent in a poultry health assistant for smallholder farmers in Kenya. Your job is to search the web for CURRENT, real information relevant to a farmer's question — such as recent disease outbreaks, alerts from authorities, weather-related risks, or poultry health news in Kenya and East Africa.

Rules:
- The farmer is in Kenya. Include "Kenya" (or the county they mention) in your searches unless they ask about another place.
- Do not narrate your searching. Do not write things like "let me search" or "search result 7". Search silently, then write only your final answer to the farmer.
- Only report what you actually find in your search results. Never guess or make up information.
- If you find nothing relevant or recent, say so clearly rather than inventing an answer. Say "I found no reports of..." rather than "there has been no...", because not finding a report does not prove something did not happen.
- Use today's date (given in the message) to judge how recent information is. Always say when a report is from (month and year). If the most recent information you find is more than 6 months old, say clearly that you could not find recent reports.
- Prefer official and reliable sources (government ministries, county governments, FAO, WOAH, established news outlets) over blogs or forums.
- Say where information came from in plain words (e.g. "according to a Ministry of Agriculture statement from March 2026"). The app lists the links separately, so do not paste long web addresses.
- Keep answers short and practical for a farmer, not technical or academic. End with what the farmer could do with this information.
- If asked about anything unrelated to poultry or farming, politely redirect to that topic.

SAFETY:
- NEVER give medicine doses, mixing rates, treatment durations or brand names, even if a website mentions them. Say that a vet, livestock officer or registered agrovet should advise on medicines, and that the product label must be followed.
- NEVER invent phone numbers, hotlines or organisation names. If the farmer needs a vet, say they can find local contacts in the "Find help near you" section of this app's sidebar.
- If the farmer describes sick or dying birds, suggest they also use the Diagnose mode in this app and contact a vet or the county veterinary office.
- If reports mention bird flu (avian influenza), remind farmers not to handle sick or dead birds with bare hands, to keep children away, and to report unusual deaths to the county veterinary office.
- Stay calm and measured. No alarming language or words in capitals.

LANGUAGE: Reply in the same language the farmer writes in. If they write in Swahili, reply in simple, everyday Swahili."""


def _collect_sources(content_blocks):
    """Pull the web links Claude actually cited, without duplicates."""
    sources = []
    seen = set()
    for block in content_blocks:
        if block.type != "text":
            continue
        for citation in (getattr(block, "citations", None) or []):
            url = getattr(citation, "url", None)
            if url and url not in seen:
                seen.add(url)
                title = getattr(citation, "title", None) or url
                sources.append((title, url))
    return sources


def _final_answer_blocks(all_blocks):
    """Keep only the text written after the last web search — the real answer,
    not the agent's notes to itself between searches."""
    last_search = -1
    for i, block in enumerate(all_blocks):
        if block.type in ("server_tool_use", "web_search_tool_result"):
            last_search = i
    return [b for b in all_blocks[last_search + 1:] if b.type == "text"]


def run_research_agent(user_question):
    message = f"Today's date: {date.today().isoformat()}\n\nFarmer's question: {user_question}"
    messages = [{"role": "user", "content": message}]
    all_blocks = []

    for _ in range(MAX_CONTINUATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=RESEARCH_SYSTEM_PROMPT,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_SEARCHES
            }],
            messages=messages
        )
        all_blocks.extend(response.content)

        # A long search can pause part-way; send it back so it can finish
        if response.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": response.content}]
            continue
        break

    answer_blocks = _final_answer_blocks(all_blocks)
    reply_text = "".join(block.text for block in answer_blocks).strip()
    if not reply_text:
        reply_text = "Sorry, I could not find an answer right now. Please try asking in a different way."

    sources = _collect_sources(answer_blocks)
    if sources:
        reply_text += "\n\n**Sources:**\n" + "\n".join(
            f"- [{title}]({url})" for title, url in sources[:6]
        )

    return reply_text


if __name__ == "__main__":
    test_question = "Are there any recent reports of poultry disease outbreaks in Kenya?"
    print(run_research_agent(test_question))