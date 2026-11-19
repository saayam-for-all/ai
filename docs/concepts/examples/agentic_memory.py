"""Rolling-memory experiment for issue #197."""

from utils import MAX_HISTORY_MESSAGES

MEMORY_BATCH_SIZE = 5


class ConversationMemory:
    """Keep recent messages while summarizing older messages in batches."""

    def __init__(self, summarizer):
        self.summarizer = summarizer
        self.memory = ""
        self.pending = []
        self.recent = []

    def add(self, message):
        """Add one message, moving expired messages toward rolling memory."""
        self.recent.append(message)

        if len(self.recent) > MAX_HISTORY_MESSAGES:
            self.pending.append(self.recent.pop(0))

        if len(self.pending) >= MEMORY_BATCH_SIZE:
            self.memory = self.summarizer(self.memory, self.pending)
            self.pending = []

    def context(self):
        """Return the compact memory and current conversation window."""
        return self.memory, self.pending + self.recent