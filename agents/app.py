import asyncio
from models import DeckInput
from workflow import Deck
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

# Use dataclass for backwards-compatible way to evolve code

async def main():
    # Create client connected to server at the given address
    client = await Client.connect("localhost:7233", namespace="default") #Temporal cluster and namespace
 
    #Execute a workflow
    handle = await client.start_workflow(
        Deck.run,
        DeckInput(content="../content/content.md"), #pass path instead of content
        id="deck-workflow-1",
        task_queue="greeting-task-queue",
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    )
    print(f"Started workflow. Workflow ID: {handle.id}, RunID: {handle.result_run_id}")

    result= await handle.result()
    print(f"Workflow result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
