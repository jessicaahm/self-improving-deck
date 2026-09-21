import argparse
import asyncio
import sys
from temporalio.client import Client

def parse_args():
    parser = argparse.ArgumentParser(
        description="Send feedback or approval to a running Deck workflow."
    )
    parser.add_argument("workflow_id", help="Workflow ID printed by app.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--feedback", help="Feedback text to send as an update")
    group.add_argument("--approve", action="store_true", help="Send the approve signal")
    return parser.parse_args()
                           

async def main():
    args = parse_args()    
    # Create client connected to server at the given address
    client = await Client.connect("localhost:7233", namespace="default") #Temporal cluster and namespace

    #Execute a workflow
    handle = client.get_workflow_handle(args.workflow_id)

    if args.approve:
        # Send approval signal to the workflow
        await handle.signal("approve")
        print("Approval signal sent.Workflow completed")
    else:
        # Wait for the workflow to complete and get the result
        result = await handle.execute_update("submit_feedback", args.feedback)
        print(f"Feedback accepted by {args.workflow_id}: {result}")

if __name__ == "__main__":
    asyncio.run(main())