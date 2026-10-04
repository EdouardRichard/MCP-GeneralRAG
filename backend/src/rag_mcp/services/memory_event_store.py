class MemoryEventStore:
    """Append-only event repository. Deliberately exposes no mutation methods."""

    def __init__(self, session):
        self.session = session

    async def append(self, event):
        self.session.add(event)
        await self.session.flush()
        return event

