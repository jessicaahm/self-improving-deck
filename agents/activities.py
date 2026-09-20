import os
import aiofiles
from temporalio import activity
from temporalio.exceptions import ApplicationError
from models import DeckInput, DeckOutput
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, ProcessError

def _as_temporal_error(e: ProcessError) -> ApplicationError:
    result = str(e)
    if "Not logged in" in result:
        return ApplicationError(
              "Claude is not logged in — run claude auth login",
              type="Unauthorized", non_retryable=True,
          )
    return ApplicationError(str(e), type="ClaudeAgentFailed")

@activity.defn
async def generate_deck(input: DeckInput) -> DeckOutput:
    # Placeholder for deck generation logic
    async with aiofiles.open(input.content, "r") as f:
        content = await f.read()
        
    activity.heartbeat()
    result_text=""
    try:
        async for message in query(
            prompt=(
            "You are a presentation designer. " 
            "Generate a self-contained HTML presentation deck (no external CSS or JS). "

            f"Content:\n\n{content}"  
            ),options=ClaudeAgentOptions(max_turns=20,model="claude-haiku-4-5")
        ):
            if isinstance(message, ResultMessage):
                result_text = message.result
                activity.logger.info(f"Received result: {result_text}")

    except ProcessError as e:
        raise _as_temporal_error(e)

    output_path = os.path.join(
        os.path.dirname(__file__), "output", f"deck_{input.workflow_id}.html"
    )
    activity.logger.info(f"Writing deck to {output_path}")
    if result_text:
        async with aiofiles.open(output_path, "w") as f:
            await f.write(result_text)
        return DeckOutput(status=200, message=f"Deck generated successfully at {output_path}")
    else:
        raise ApplicationError("Failure to generate deck", type="EmptyResult")

@activity.defn
async def revise_deck(input: DeckInput) -> str:
    deck_path = os.path.join(os.path.dirname(__file__), "output", f"deck_{input.workflow_id}.html")
    activity.heartbeat()
    result_text=""
    try:
        async for message in query(
            prompt=(
                f"You are an expert frontend designer."
                f"Revise the following HTML presentation deck based on the feedback:\n\n{input.content}\n\n." 
                f"Edit the file directly."
                f"Only edit output/deck_{input.workflow_id}.html. Do not create any other files."  
            ),
            options=ClaudeAgentOptions(
                max_turns=30,
                model="claude-haiku-4-5",
                allowed_tools=["Read","Edit","Write","WebFetch","WebSearch"],
                permission_mode="acceptEdits",
                cwd=os.path.dirname(__file__))
        ):
            if isinstance(message, ResultMessage):
                result_text = message.result
    except ProcessError as e:
            raise _as_temporal_error(e)
    return result_text