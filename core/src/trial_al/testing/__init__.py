"""Contract test suites that every implementation of a core interface must pass (design §5.6).

Importing this package needs pytest: install ``trial-al[testing]``.
"""

from trial_al.testing.source import SourceContract
from trial_al.testing.sources import FakeSource, fake_study
from trial_al.testing.storage import StorageContract

__all__ = ["FakeSource", "SourceContract", "StorageContract", "fake_study"]
