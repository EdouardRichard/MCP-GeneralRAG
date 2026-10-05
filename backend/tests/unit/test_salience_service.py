def test_salience_cold_start_decay_and_no_decay_gate():
    from rag_mcp.services.salience_service import SalienceService

    service = SalienceService()
    assert service.initial() == 0.0
    assert service.update(0.0, access_count=1, age_days=0) == 1.0
    assert service.rank_signal(1.0, decay_rate=0.0) == 0.0


def test_forced_decay_is_linear_in_inactivity_not_salience_multiplier():
    from rag_mcp.services.salience_service import SalienceService
    service = SalienceService(beta=.05)
    assert service.update(10, access_count=0, age_days=20) == 9
    assert service.update(0, access_count=0, age_days=20) == 0


def test_rank_signal_requires_explicit_decay_execution():
    from rag_mcp.services.salience_service import SalienceService
    service = SalienceService()
    assert service.rank_signal(10, decay_rate=.05) == 0
    assert service.rank_signal(10, decay_rate=.05, age_days=20) == 9

