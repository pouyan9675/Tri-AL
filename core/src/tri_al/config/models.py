"""The shape of ``tri-al.toml`` (docs/design.md §5.7)."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tri_al.config.schedule import Schedule


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class ServerConfig(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=64)  # API worker processes; one job worker runs too
    # Host names the browser may use to reach the server (the Host and Origin headers are
    # checked against them, against DNS rebinding). Empty: the local names, plus `host` if
    # it is a specific address. "*" turns the check off.
    allowed_hosts: list[str] = Field(default_factory=list)

    @property
    def is_local(self) -> bool:
        return self.host in LOCAL_HOSTS

    def hosts(self) -> frozenset[str] | None:
        """Host names the server answers to, without ports; None means any."""
        if "*" in self.allowed_hosts:
            return None
        names = {"127.0.0.1", "localhost", "[::1]", "::1"}
        if self.host not in ("0.0.0.0", "::", ""):
            names.add(self.host)
        return frozenset(names | {host.lower() for host in self.allowed_hosts})


class DataConfig(_Section):
    dir: Path = Path("data")

    @property
    def trials_db(self) -> Path:
        return self.dir / "trials.db"

    @property
    def app_db(self) -> Path:
        return self.dir / "app.db"


class UpdateConfig(_Section):
    # off, hourly, daily, weekly, "daily at 06:30" or "every 6 hours" (config/schedule.py)
    schedule: str = "daily"

    @field_validator("schedule")
    @classmethod
    def _valid_schedule(cls, value: str) -> str:
        Schedule.parse(value)
        return value

    @property
    def parsed_schedule(self) -> Schedule:
        return Schedule.parse(self.schedule)


class PluginSection(BaseModel):
    """A ``[plugins.<name>]`` section.

    ``enabled`` belongs to the core; every other key is the plugin's own settings, which its
    settings model validates when the plugin loads. Installed plugins are enabled unless their
    section says ``enabled = false``.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Config(_Section):
    server: ServerConfig = Field(default_factory=ServerConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    update: UpdateConfig = Field(default_factory=UpdateConfig)
    plugins: dict[str, PluginSection] = Field(default_factory=dict)

    def plugin_enabled(self, name: str) -> bool:
        section = self.plugins.get(name)
        return section is None or section.enabled

    def plugin_settings(self, name: str) -> dict[str, Any]:
        section = self.plugins.get(name)
        return {} if section is None else section.settings
