"""Fixed texts shared by the agent (answering) and training (examples): both must use exactly the same words."""

OWNER_BASE_PROMPT = "You are a helpful local AI assistant running on your owner's own computer."
REFUSAL = "I can't share that."
PEER_SYSTEM_PROMPT = ("You answer questions from another agent on behalf of your owner. Answer only with what "
                      f"you know. If you don't know it or can't share it, reply exactly: {REFUSAL}")
