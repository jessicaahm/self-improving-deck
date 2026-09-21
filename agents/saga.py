from temporalio import workflow

class Saga:
    def __init__(self):
        self._compensations = []

    def add(self, fn):
        self._compensations.append(fn)

    async def compensate(self):
        for fn in reversed(self._compensations):   # LIFO
            try:
                await fn()
            except Exception as e:
                workflow.logger.warning(f"compensation failed, continuing: {e}")
        self._compensations.clear()