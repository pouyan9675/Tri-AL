"""Results posted to ClinicalTrials.gov: who took part, safety, and each trial's results.

About one trial in eight has results posted: the participant flow, baseline characteristics
(race, ethnicity, sex, age), outcome measures with their analyses, and adverse events by
arm. The plugin keeps what charts need in its own tables (``store``), brought up to date
before each precompute of the charts, and adds two sections to the analysis page's
Landscape: who took part, and safety (``charts``). A trial's page shows its results from
``/api/x/results/trials/{source_id}`` (``api``), read from the trial's raw document.
Settings, in ``tri-al.toml``:

    [plugins.results]
    top = 20  # rows in the most-reported serious events table
"""

from importlib.metadata import version

from pydantic import BaseModel, ConfigDict, Field

from tri_al.plugins import Plugin, Registry
from tri_al.stats import Derived
from tri_al_results.api import router
from tri_al_results.charts import charts
from tri_al_results.store import MIGRATIONS, build_results


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top: int = Field(default=20, ge=1, le=100)


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    registry.add_migrations("trials", MIGRATIONS)
    registry.add_derived(Derived(name="results", build=build_results))
    for chart in charts(top=settings.top):
        registry.add_chart(chart)
    registry.add_routes(router)


plugin = Plugin(
    name="results",
    version=version("tri-al-results"),
    api_version=1,
    register=register,
    settings=Settings,
    description="Results: who took part, safety, and each trial's posted results.",
)

__all__ = ["Settings", "plugin"]
