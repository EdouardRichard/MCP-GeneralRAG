import pytest
from sqlalchemy import literal, select

from rag_mcp.db import get_session_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", [1, 2])
async def test_global_database_connections_do_not_outlive_the_test_event_loop(iteration):
    async with get_session_factory()() as session:
        assert await session.scalar(select(literal(iteration))) == iteration
