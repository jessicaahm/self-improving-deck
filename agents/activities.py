import os
import aiofiles
from temporalio import activity
from models import DeckInput, DeckOutput
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

@activity.defn
async def generate_deck(input: DeckInput) -> str:
    # Placeholder for deck generation logic
    async with aiofiles.open(input.content, "r") as f:
        content = await f.read()
        
    activity.heartbeat()
    result_text=""
    async for message in query(
        prompt=(
          "You are a presentation designer. " 
          "Generate a self-contained HTML presentation deck (no external CSS or JS). "
          "Output ONLY raw HTML — no explanation, no markdown fences. "
          f"Content:\n\n{content}"  
        ),options=ClaudeAgentOptions(max_turns=20)
    ):
        if isinstance(message, ResultMessage):
            result_text = message.result

    output_path = os.path.join(
        os.path.dirname(__file__), "output", "deck.html"
    )

    print(result_text)

    if result_text:
        async with aiofiles.open(output_path, "w") as f:
            await f.write(result_text)
        return DeckOutput(status=200, message=f"Deck generated successfully at {output_path}")
    else:
        return DeckOutput(status=500, message="Failed to generate deck.")