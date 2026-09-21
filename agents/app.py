import asyncio
import os
import uuid
from models import DeckInput
from workflow import Deck
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

# Use dataclass for backwards-compatible way to evolve code

async def main():
    # Create client connected to server at the given address
    client = await Client.connect("localhost:7233", namespace="default") #Temporal cluster and namespace
    CONTENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "content", "content.md")
    #Execute a workflow
    handle = await client.start_workflow(
        Deck.run,
        DeckInput(content=CONTENT_PATH), #pass path instead of content
        id=f"deck-workflow-{uuid.uuid4().hex[:8]}",
        task_queue="greeting-task-queue",
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    )
    print(f"Started workflow. Workflow ID: {handle.id}, RunID: {handle.result_run_id}")

    result= await handle.result()
    print(f"Workflow result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
