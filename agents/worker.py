import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from workflow import Deck
from activities import generate_deck

async def main():
    client = await Client.connect("localhost:7233", namespace="default") #Temporal cluster and namespace
    worker = Worker(client, task_queue="greeting-task-queue", workflows=[Deck], activities=[generate_deck]) #Create Worker instance with the client, task queue, and workflow
    print("Worker started.")
    await worker.run() #Start the worker and poll for tasks

if __name__ == "__main__":
    asyncio.run(main())
