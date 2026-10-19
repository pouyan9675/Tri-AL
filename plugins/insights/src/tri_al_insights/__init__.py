"""Research Intelligence: analysis on top of the counts, in its own dashboard section.

Emerging research trends (``trends``) and a map of recently registered trials by what
they're about (``clusters``: UMAP and HDBSCAN over the trial vectors, laid out once per data
version), on the dashboard; the same map in 3-D on the analysis page. All are precomputed
with each update and follow the page's filter. Settings, in ``tri-al.toml``:

    [plugins.insights]
    windows = [3, 6]      # months
    baseline_months = 12  # compared with this many months before each window
    top = 10              # entries per list
    min_trials = 3        # trials an entry needs in the window ...
    min_sponsors = 2      # ... from at least this many lead sponsors
    cluster_months = 12        # the map's trials: first posted in the last 12 months
    cluster_min_size = 350     # trials a cluster needs: about 40 clusters for a year
    cluster_min_samples = 25
    cluster_dimensions = 10    # clusters are found in a layout with this many dimensions
    cluster_neighbors = 15
    cluster_min_dist = 0.1
    cluster_max_points = 3000  # drawn; every trial is still laid out and clustered
    cluster_3d = true          # also lay them out in 3-D, for the analysis page
    cluster_max_points_3d = 20000
"""

from importlib.metadata import version
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tri_al.filters import TrialFilter
from tri_al.plugins import Plugin, Registry
from tri_al.stats import Chart, ChartContext, Derived, Layout, Rows
from tri_al_insights.clusters import (
    MIGRATIONS,
    ClusterOptions,
    build_landscape,
    research_clusters,
    research_landscape_3d,
)
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
    cluster_months: int = Field(default=12, ge=1, le=36)
    cluster_min_size: int = Field(default=350, ge=2, le=5_000)
    cluster_min_samples: int = Field(default=25, ge=1, le=1_000)
    cluster_dimensions: int = Field(default=10, ge=2, le=50)
    cluster_neighbors: int = Field(default=15, ge=2, le=200)
    cluster_min_dist: float = Field(default=0.1, ge=0, le=1)
    cluster_max_points: int = Field(default=3_000, ge=100, le=20_000)
    cluster_3d: bool = True
    cluster_max_points_3d: int = Field(default=20_000, ge=1_000, le=100_000)

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

    def cluster_options(self) -> ClusterOptions:
        return ClusterOptions(
            months=self.cluster_months,
            min_cluster_size=self.cluster_min_size,
            min_samples=self.cluster_min_samples,
            dimensions=self.cluster_dimensions,
            neighbors=self.cluster_neighbors,
            min_dist=self.cluster_min_dist,
            max_points=self.cluster_max_points,
            windows=tuple(self.windows),
            solid=self.cluster_3d,
            max_points_3d=self.cluster_max_points_3d,
        )


def charts(settings: Settings) -> list[Chart]:
    options = settings.options()
    cluster_options = settings.cluster_options()

    def trends(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return emerging(ctx, filter, options)

    def clusters(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return research_clusters(ctx, filter, cluster_options)

    def landscape_3d(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return research_landscape_3d(ctx, filter, cluster_options)

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
        Chart(
            id="research_clusters",
            title="Clinical research landscape",
            widget="scatter",
            query=clusters,
            section=SECTION,
            layout=Layout(width=4, height=3, order=210),
            x="x",
            y="y",
            description=(
                f"Trials first posted in the last {settings.cluster_months} months, placed by "
                "what they're about; each cluster is named after its most distinctive MeSH term."
            ),
        ),
        Chart(
            id="research_landscape_3d",
            title="Research landscape in 3D",
            widget="scatter3d",
            query=landscape_3d,
            page="analysis",
            layout=Layout(width=4, height=3, order=100),
            x="x",
            y="y",
            description=(
                f"Trials first posted in the last {settings.cluster_months} months, placed in "
                "three dimensions by their embeddings: trials close together are about similar "
                "things. Clusters and colours are the dashboard map's."
            ),
        ),
    ]


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    options = settings.cluster_options()
    registry.add_migrations("trials", MIGRATIONS)
    registry.add_derived(
        Derived(
            name="landscape", build=lambda conn, version: build_landscape(conn, version, options)
        )
    )
    for chart in charts(settings):
        registry.add_chart(chart)


plugin = Plugin(
    name="insights",
    version=version("tri-al-insights"),
    api_version=1,
    register=register,
    settings=Settings,
    description="Research Intelligence: emerging trends and a map of recent trials.",
)

__all__ = ["SECTION", "Settings", "charts", "plugin"]
