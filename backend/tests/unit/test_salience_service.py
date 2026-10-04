def test_salience_cold_start_decay_and_no_decay_gate():
    from rag_mcp.services.salience_service import SalienceService

    service = SalienceService()
    assert service.initial() == 0.0
    assert service.update(0.0, access_count=1, age_days=0) == 1.0
    assert service.rank_signal(1.0, decay_rate=0.0) == 0.0

