"""Research Intelligence: analysis on top of the counts, in its own dashboard section.

For now, emerging research trends: the conditions and interventions whose share of newly
registered trials grew the most in the last 3 and 6 months, against the year before
(``tri_al_insights.trends`` explains the method). Like every chart, it is precomputed with
each update and follows the dashboard's filter. Settings, in ``tri-al.toml``:

    [plugins.insights]
    windows = [3, 6]      # months
    baseline_months = 12  # compared with this many months before each window
    top = 10              # entries per list
    min_trials = 3        # trials an entry needs in the window ...
    min_sponsors = 2      # ... from at least this many lead sponsors
"""

from importlib.metadata import version
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tri_al.filters import TrialFilter
from tri_al.plugins import Plugin, Registry
from tri_al.stats import Chart, ChartContext, Layout, Rows
from tri_al_insights.trends import Options, emerging

SECTION = "Research Intelligence"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: list[Annotated[int, Field(ge=1, le=12)]] = Field(
        default=[3, 6], min_length=1, max_length=4
    )
    baseline_months: int = Field(default=12, ge=3, le=36)
    top: int = Field(default=10, ge=1, le=50)
    min_trials: int = Field(default=3, ge=1, le=100)
    min_sponsors: int = Field(default=2, ge=1, le=20)

    @field_validator("windows")
    @classmethod
    def _distinct(cls, windows: list[int]) -> list[int]:
        return sorted(set(windows))

    def options(self) -> Options:
        return Options(
            windows=tuple(self.windows),
            baseline=self.baseline_months,
            top=self.top,
            min_trials=self.min_trials,
            min_sponsors=self.min_sponsors,
        )


def charts(settings: Settings) -> list[Chart]:
    options = settings.options()

    def trends(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return emerging(ctx, filter, options)

    return [
        Chart(
            id="emerging_trends",
            title="Emerging research trends",
            widget="trends",
            query=trends,
            section=SECTION,
            layout=Layout(width=4, height=2, order=200),
            description=(
                "Conditions and interventions taking a growing share of newly registered "
                f"trials, against the {settings.baseline_months} months before."
            ),
        ),
    ]


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    for chart in charts(settings):
        registry.add_chart(chart)


plugin = Plugin(
    name="insights",
    version=version("tri-al-insights"),
    api_version=1,
    register=register,
    settings=Settings,
    description="Research Intelligence: emerging research trends on the dashboard.",
)

__all__ = ["SECTION", "Settings", "charts", "plugin"]
