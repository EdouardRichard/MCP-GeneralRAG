def start_work(*, digest=None, working_set=None, budget="standard"):
    return {"digest": digest or [], "working_set": working_set or [], "budget": budget, "read_guidance": ""}
