"""Process-local conversational state (chat history, pending question per client)."""
HISTORY: dict[str, list] = {}
PENDING_QUESTION: dict[str, str] = {}
