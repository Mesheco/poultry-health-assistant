import os
import io
from datetime import date
import pandas as pd
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-5"

MONITOR_PROMPT = """You are the Monitoring agent in a poultry health assistant for smallholder farmers in Kenya. You receive a farmer's daily flock log as a CSV table, plus KEY FACTS that were calculated by the app. Your job is to look for early warning signs of illness, before birds become obviously sick.

The log columns are: date, total_birds (birds in the flock at the START of that day, before that day's deaths), deaths (birds that died that day), eggs (eggs collected), feed_kg, water_litres, symptoms (the farmer's notes). A value of 0 for eggs, feed or water may simply mean it was not recorded; do not treat it as a real drop unless the pattern makes that clear.

IMPORTANT: The KEY FACTS were calculated exactly by the app. Always use them for totals, percentages and changes. Do not do your own arithmetic for these; quote the KEY FACTS instead. Use today's date (given in the message) when saying "today" or "yesterday".

Analyse the log and look for:
- Deaths: any rise over recent days, and total deaths as a share of the flock.
- Water and feed: drops compared to earlier days. A fall in water or feed intake is often one of the earliest signs of disease, sometimes appearing a day or two before visible symptoms.
- Eggs: a drop in egg production.
- Symptoms notes: anything that is appearing or getting worse.
- Several signals moving together (e.g. more deaths plus less water) are more worrying than one on its own.

Reply in this structure, briefly and in plain language:
1. Overall picture: one or two sentences.
2. Warning signs: each with the actual numbers (e.g. "water fell from 40 L to 27 L"). If there are none, say so.
3. What is going well, if anything.
4. What to do next: a short plan for the next few days. If there are warning signs, suggest the farmer switch to the Diagnose mode in this app and describe the symptoms, and consider contacting a vet or livestock officer.
5. If there are fewer than 3 days of entries, gently mention that trends become clearer with more days of records.

Then, on its own line, output exactly one of: [URGENCY:LOW] or [URGENCY:MEDIUM] or [URGENCY:HIGH]

Always end with this exact disclaimer: "This is not a substitute for professional veterinary diagnosis. Please consult a licensed veterinarian or livestock officer, especially for urgent or high-mortality situations."

LANGUAGE: Reply in English, unless the farmer's symptoms notes are written in Swahili, in which case reply in simple, everyday Swahili (including the disclaimer). Always keep the urgency tag in English exactly as shown.

RULES:
- Only use numbers that are in the log or the KEY FACTS. Never invent data.
- Do not name a specific disease as certain; this agent spots trends, and diagnosis happens in the Diagnose mode or with a vet.
- Never phrase medication as a direct command; use "you could consider..." or "a vet may recommend...".
- Stay calm and measured. No all-caps or alarming language."""


def _change_text(label, first, last, unit):
    """Describe the change between the first and last recorded values, e.g. 'Water: 40 L -> 27 L (down 32%)'."""
    if first is None or last is None or first == 0:
        return f"{label}: not enough recorded data to compare"
    pct = round((last - first) / first * 100)
    direction = "up" if pct > 0 else "down" if pct < 0 else "no change"
    pct_text = f" {abs(pct)}%" if pct != 0 else ""
    return f"{label}: {first:g}{unit} on the first day -> {last:g}{unit} on the latest day ({direction}{pct_text})"


def _first_last_nonzero(series):
    values = [v for v in series if pd.notna(v) and v > 0]
    if not values:
        return None, None
    return values[0], values[-1]


def calculate_key_facts(log_csv):
    """Do all the arithmetic in Python so the numbers are always correct."""
    df = pd.read_csv(io.StringIO(log_csv))
    for col in ["total_birds", "deaths", "eggs", "feed_kg", "water_litres"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("date")

    days = len(df)
    starting_birds = df["total_birds"].iloc[0]
    total_deaths = int(df["deaths"].fillna(0).sum())
    death_pct = round(total_deaths / starting_birds * 100, 1) if starting_birds else 0
    birds_now = int(df["total_birds"].iloc[-1] - (df["deaths"].iloc[-1] if pd.notna(df["deaths"].iloc[-1]) else 0))
    deaths_by_day = ", ".join(f"{d}: {int(x) if pd.notna(x) else 0}" for d, x in zip(df["date"], df["deaths"]))

    water_first, water_last = _first_last_nonzero(df["water_litres"])
    feed_first, feed_last = _first_last_nonzero(df["feed_kg"])
    eggs_first, eggs_last = _first_last_nonzero(df["eggs"])

    facts = [
        f"Days logged: {days} (from {df['date'].iloc[0]} to {df['date'].iloc[-1]})",
        f"Birds at the start of the log: {int(starting_birds)}",
        f"Total deaths over the whole log: {total_deaths} ({death_pct}% of the starting flock)",
        f"Estimated birds remaining after the latest day: {birds_now}",
        f"Deaths per day: {deaths_by_day}",
        _change_text("Water", water_first, water_last, " L"),
        _change_text("Feed", feed_first, feed_last, " kg"),
        _change_text("Eggs", eggs_first, eggs_last, ""),
    ]
    return "\n".join("- " + f for f in facts)


def run_monitor_agent(log_csv):
    """Send the flock log plus calculated key facts to Claude and return its trend analysis."""
    key_facts = calculate_key_facts(log_csv)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=MONITOR_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Today's date: {date.today().isoformat()}\n"
                "Here is my daily flock log. Please check it for warning signs.\n\n"
                "KEY FACTS (calculated by the app — use these numbers):\n"
                f"{key_facts}\n\n"
                "FULL LOG (CSV):\n"
                f"{log_csv}"
            )
        }]
    )
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()