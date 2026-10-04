BUILTIN_MEMORY_POLICY = {
    key: {"quota": 5000, "decay_rate": 0.05, "ttl_days": {"episodic": 180, "semantic": None, "procedural": None}}
    for key in ("se-project", "generic", "personal", "legal")
}
