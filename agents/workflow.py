from temporalio import workflow
from models import DeckInput
from datetime import timedelta

@workflow.defn
class Deck:
    @workflow.run
    async def run(self, input: DeckInput) -> str:
        # This is a placeholder for the actual workflow logic
        result = await workflow.execute_activity(
            "generate_deck",
            input,
            start_to_close_timeout=timedelta(minutes=3),
        )
        return f"Running deck: {result}"