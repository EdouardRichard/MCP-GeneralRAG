"""Read-only consolidation agent boundary."""
from rag_mcp.agents.base import AgentBase


class MemoryDistiller(AgentBase):
    def __init__(self, llm_client=None):
        super().__init__()

    def execute(self, context):
        raise NotImplementedError

    def fallback(self, context):
        raise NotImplementedError
