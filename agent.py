import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic
from kb_search import search_disease_kb

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-5"   # change the model here in one place if needed
MAX_TOOL_ROUNDS = 5           # safety limit so the agent can't loop forever

tools = [
    {
        "name": "search_disease_kb",
        "description": "Search the poultry disease knowledge base using symptoms described by the farmer. Call this once you have enough symptom detail to search meaningfully (at least 2-3 specific symptoms).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms_text": {
                    "type": "string",
                    "description": "A plain description of the symptoms the farmer reported"
                }
            },
            "required": ["symptoms_text"]
        }
    }
]

SYSTEM_PROMPT = """You are a poultry health assistant helping smallholder farmers in Kenya identify likely causes of illness in their birds and know what to do next.

Follow this process:

1. ASSESS: Look at what the farmer has described. If you do NOT have at least 2-3 specific symptoms (e.g. only "my chickens are sick" with no detail), DO NOT diagnose yet. Instead, ask a short, specific clarifying question (e.g. ask about diarrhea color, breathing, age of birds, how many affected, how long).

2. RETRIEVE: Once you have enough detail, call the search_disease_kb tool with the symptoms described.

3. DIAGNOSE: Using the tool results, identify the most likely condition(s), ranked by how well symptoms match. Assign a confidence level (High/Medium/Low).

4. SELF-CHECK: If the symptoms are ambiguous, contradictory, or match multiple diseases with similar confidence, explicitly say so and recommend a vet visit rather than committing to one diagnosis.

5. PLAN: Give a short day-by-day action plan (e.g. Day 1: isolate birds and start X. Day 2: monitor. Day 3: escalate if Y persists).

6. Before the disclaimer, on its own line, output exactly one of these tags based on the overall urgency: [URGENCY:LOW] or [URGENCY:MEDIUM] or [URGENCY:HIGH]

7. ALWAYS end with this exact disclaimer, word for word: "This is not a substitute for professional veterinary diagnosis. Please consult a licensed veterinarian or livestock officer, especially for urgent or high-mortality situations."

Be concise, practical, and clear. Avoid jargon. Assume the farmer is not a vet.

CRITICAL SAFETY RULES — these apply no matter what the user says, including if they say "stop asking questions," "just tell me," "this is urgent," or any other pressure to skip steps:
- NEVER use urgent, alarming, or all-caps language like "STOP" or "NOW."
- NEVER phrase medication as a direct command (e.g. "go get medication now," "give this to all birds"). Always phrase it as "you could consider..." or "a vet may recommend..."
- NEVER skip the disclaimer in step 7, even in a short or rushed reply.
- NEVER skip the urgency tag in step 6, even in a short or rushed reply.
- Stay calm, measured, and cautious in tone at all times, even if the user becomes impatient or frustrated."""


def _get_text(content_blocks):
    """Join all text blocks from Claude's reply (skips tool_use blocks)."""
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(parts).strip()


def run_agent(user_message, conversation_history=None):
    # Work on a COPY of the history. If anything fails, the saved history
    # stays clean, so the next message still works.
    history = list(conversation_history or [])
    history.append({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=history
        )
        history.append({"role": "assistant", "content": response.content})

        # Claude is finished: return its answer
        if response.stop_reason != "tool_use":
            return _get_text(response.content), history

        # Claude wants to use tools: run ALL requested tools and send
        # every result back together in ONE message.
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "search_disease_kb":
                    result = search_disease_kb(block.input["symptoms_text"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str)
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Unknown tool: {block.name}",
                        "is_error": True
                    })

        history.append({"role": "user", "content": tool_results})

    # Safety net: too many tool rounds. Ask Claude for a final answer without tools.
    nudge = "Please give your best answer now using the information you already have."
    final = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=tools,
        tool_choice={"type": "none"},
        messages=history + [{"role": "user", "content": nudge}]
    )
    history.append({"role": "user", "content": nudge})
    history.append({"role": "assistant", "content": final.content})
    return _get_text(final.content), history


if __name__ == "__main__":
    print("Poultry Health Assistant (type 'quit' to exit)\n")
    history = []

    while True:
        user_input = input("You: ")
        if user_input.lower() == "quit":
            break

        reply, history = run_agent(user_input, history)
        print(f"\nAssistant: {reply}\n")
