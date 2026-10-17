"""ClinicalTrials.gov source plugin for Tri-AL (docs/design.md §7 and §8).

``tri-al install`` downloads the bulk JSON zip and reads every study from it;
``tri-al update`` fetches the studies posted since the last update from API v2.
Settings, in ``tri-al.toml``:

    [plugins.ctgov]
    base_url = "https://clinicaltrials.gov/api/v2"
    page_size = 1000   # studies per API page, at most 1000
    timeout = 60       # seconds
"""

from importlib.metadata import version

from pydantic import BaseModel, ConfigDict, Field

from tri_al.plugins import Plugin, Registry
from tri_al_ctgov.source import BASE_URL, MAX_PAGE_SIZE, CtgovSource


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = BASE_URL
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    timeout: float = Field(default=60.0, gt=0)


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    registry.add_source(
        CtgovSource(
            base_url=settings.base_url, page_size=settings.page_size, timeout=settings.timeout
        )
    )


plugin = Plugin(
    name="ctgov",
    version=version("tri-al-ctgov"),
    api_version=1,
    register=register,
    settings=Settings,
    description="ClinicalTrials.gov: installs from the bulk JSON download, updates from API v2.",
)

__all__ = ["CtgovSource", "Settings", "plugin"]
