from dotenv import load_dotenv
import os
from anthropic import Anthropic

# Load the API key from your .env file
load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Say hello and confirm you're working, in one short sentence."}
    ]

)

print(response.content[0].text)
