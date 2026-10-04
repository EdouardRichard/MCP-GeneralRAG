from pathlib import Path


def test_frontend_memory_page_and_api_exist():
    root = Path(__file__).parents[3] / "frontend/src"
    assert (root / "pages/MemoriesPage.tsx").exists()
    assert (root / "api/memories.ts").exists()
