"""Quick connectivity check: PydanticAI → Ollama (OpenAI-compat endpoint)."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

load_dotenv(Path(__file__).parent / ".env")
model_name = os.getenv("OLLAMA_MODEL", "mistral-small:22b")
ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")

# OllamaProvider passes base_url straight to AsyncOpenAI (no /v1 appended automatically).
# The Ollama OpenAI-compat endpoint is always at <host>/v1.
base_url = "http://" + ollama_url.split("://", 1)[-1].split("/")[0] + "/v1"

model = OpenAIChatModel(model_name, provider=OllamaProvider(base_url=base_url))
agent = Agent(model=model, system_prompt="You are a test agent. Reply with one short sentence.")


async def main():
    print(f"🔍 Testing PydanticAI → Ollama ({model_name}) ...")
    result = await agent.run("Say hello in one sentence.")
    print("✅ Connection OK")
    print(f"Reply: {result.output}")


asyncio.run(main())
