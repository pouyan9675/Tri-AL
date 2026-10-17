"""Contract test suites that every implementation of a core interface must pass (design §5.6).

Importing this package needs pytest: install ``trial-al[testing]``.
"""

from trial_al.testing.storage import StorageContract

__all__ = ["StorageContract"]
