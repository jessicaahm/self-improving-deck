import asyncio
import os
import shutil
import aiofiles
from contextlib import asynccontextmanager
from temporalio import activity
from temporalio.exceptions import ApplicationError
from models import DeckInput, DeckOutput, SnapshotResult, RestoreResult
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, ProcessError

@asynccontextmanager
async def _heartbeat_every(seconds: float):
    """Heartbeat on a fixed cadence while a long Claude call runs."""
    async def _beat():
        while True:
            activity.heartbeat()
            await asyncio.sleep(seconds)    
    task = asyncio.create_task(_beat())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

def _deck_path(workflow_id: str) -> str:
    return os.path.join(os.path.dirname(__file__), "output", f"deck_{workflow_id}.html")

def _backup_path(workflow_id: str) -> str:
    return os.path.join(os.path.dirname(__file__), "output", f"deck_{workflow_id}-backup.html")

def _as_temporal_error(e: ProcessError) -> ApplicationError:
    result = str(e)
    activity.logger.info("Error in Claude:", str(e))
    if "Not logged in" in result:
        return ApplicationError(
              "Claude is not logged in — run claude auth login",
              type="Unauthorized", non_retryable=True,
          )
    return ApplicationError(str(e), type="ClaudeAgentFailed")

@activity.defn
async def snapshot_deck(input: DeckInput) -> SnapshotResult:
    #Run some code
    src, dst = _deck_path(input.workflow_id), _backup_path(input.workflow_id)
    if not os.path.exists(src):
        return SnapshotResult(created=False)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    activity.logger.info(f"Deck snapshot created at {dst}")
    return SnapshotResult(created=True, path=dst)

@activity.defn
async def restore_deck(input: DeckInput) -> RestoreResult:
    backup, deck = _backup_path(input.workflow_id), _deck_path(input.workflow_id)
    if not os.path.exists(backup):
        activity.logger.info("No backup to restore.")
        return RestoreResult(restored=False)
    tmp = deck + ".tmp"
    shutil.copyfile(backup, tmp)
    os.replace(tmp, deck)
    activity.logger.info(f"Deck restored from {backup}")
    return RestoreResult(restored=True, path=deck)

@activity.defn
async def delete_deck(input: DeckInput) -> bool:
    targets = [_deck_path(input.workflow_id)]
    if input.delete_all:
        targets.append(_backup_path(input.workflow_id))
        targets.extend(p + ".tmp" for p in targets.copy())
    removed = False
    for path in targets:
        if os.path.exists(path):
            os.remove(path)
            removed = True
    activity.logger.info(f"delete_deck removed files: {removed}")
    return removed

@activity.defn
async def generate_deck(input: DeckInput) -> DeckOutput:
    # Placeholder for deck generation logic 
    result_text=""
    try:
        async with aiofiles.open(input.content, "r") as f:
                content = await f.read()  

        async for message in query(
            prompt=(
            "You are a presentation designer. " 
            "Generate a self-contained HTML presentation deck (no external CSS or JS). "
            "Do not use tools. Do not write files. Output raw HTML starting with <!DOCTYPE html>, no markdown fences. "
            f"Content:\n\n{content}"  
            ),options=ClaudeAgentOptions(max_turns=20,model="claude-sonnet-5", setting_sources=[])
        ):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    raise ApplicationError(f"revise failed: {message.subtype} {message.errors}", type="ClaudeAgentFailed")
                result_text = message.result
                activity.logger.info(f"Received result: {result_text}")

        output_path = _deck_path(input.workflow_id)
        activity.logger.info(f"Writing deck to {output_path}")
        if result_text:
            tmp = output_path + ".tmp"
            async with aiofiles.open(tmp, "w") as f:
                await f.write(result_text)
            os.replace(tmp, output_path)
            return DeckOutput(status=200, message=f"Deck generated successfully at {output_path}")
        else:
            raise ApplicationError("Failure to generate deck", type="EmptyResult")

    except ProcessError as e:
        raise _as_temporal_error(e)

    

@activity.defn
async def revise_deck(input: DeckInput) -> str:
    deck_path = _deck_path(input.workflow_id)
    backup_path = _backup_path(input.workflow_id)
    result_text=""

    # Every attempt starts from the snapshot, so a retry never
    # builds on a half-finished edit from a previous attempt.
    if os.path.exists(backup_path):
        tmp = deck_path + ".tmp"
        shutil.copyfile(backup_path, tmp)
        os.replace(tmp, deck_path)
        activity.logger.info(
            f"Attempt {activity.info().attempt}: reset deck from snapshot"
        )

    try:
        async with _heartbeat_every(2):
            async for message in query(
                prompt=(
                    f"You are an expert frontend designer."
                    f"Revise the following HTML presentation deck based on the feedback:\n\n{input.content}\n\n." 
                    f"Edit the file directly."
                    f"Only edit {deck_path}. Do not create any other files."  
                ),
                options=ClaudeAgentOptions(
                    max_turns=30,
                    model="claude-sonnet-5",
                    allowed_tools=["Read","Edit","Write","WebFetch","WebSearch"],
                    permission_mode="acceptEdits",
                    cwd=os.path.dirname(__file__))
            ):
                if isinstance(message, ResultMessage):
                    if message.is_error:
                        raise ApplicationError(f"revise failed: {message.subtype} {message.errors}", type="ClaudeAgentFailed")
                    result_text = message.result
    except ProcessError as e:
            raise _as_temporal_error(e)
    return result_text
