import asyncio
import sys
from temporalio.client import Client

async def main():
    # Create client connected to server at the given address
    client = await Client.connect("localhost:7233", namespace="default") #Temporal cluster and namespace

    #Execute a workflow
    handle = client.get_workflow_handle("deck-workflow-2")

    if "--approve" in sys.argv:
        # Send approval signal to the workflow
        await handle.signal("approve")
        print("Approval signal sent.Workflow completed")
    else:
        # Wait for the workflow to complete and get the result
        feedback = sys.argv[1]
        result = await handle.execute_update("submit_feedback", feedback)

if __name__ == "__main__":
    asyncio.run(main())