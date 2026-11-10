"""Memory store errors shared by the store and its callers."""


class VersionConflict(RuntimeError):
    """Raised when saved memory has changed since it was loaded."""