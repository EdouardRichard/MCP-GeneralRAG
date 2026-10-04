def management_action(action, *, actor):
    return {"authorized": actor == "management", "action": action}
