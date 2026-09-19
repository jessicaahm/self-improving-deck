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

          f"Content:\n\n{content}"  
        ),options=ClaudeAgentOptions(max_turns=20)
    ):
        if isinstance(message, ResultMessage):
            result_text = message.result

    output_path = os.path.join(
        os.path.dirname(__file__), "output", f"deck_{input.workflow_id}.html"
    )

    print(result_text)

    if result_text:
        async with aiofiles.open(output_path, "w") as f:
            await f.write(result_text)
        return DeckOutput(status=200, message=f"Deck generated successfully at {output_path}")
    else:
        return DeckOutput(status=500, message="Failed to generate deck.")

@activity.defn
async def revise_deck(input: DeckInput) -> str:
    deck_path = os.path.join(os.path.dirname(__file__), "output", f"deck_{input.workflow_id}.html")
    activity.heartbeat()
    result_text=""
    async for message in query(
        prompt=(
            f"You are an expert frontend designer."
            f"Revise the following HTML presentation deck based on the feedback:\n\n{input.content}\n\n." 
            f"Edit the file directly."
            f"Only edit output/deck_{input.workflow_id}.html. Do not create any other files."  
        ),
        options=ClaudeAgentOptions(
            max_turns=30,
            allowed_tools=["Read","Edit","Write","WebFetch","WebSearch"],
            permission_mode="acceptEdits",
            cwd=os.path.dirname(__file__))
    ):
        if isinstance(message, ResultMessage):
            result_text = message.result

    return result_text