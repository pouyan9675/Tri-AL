"""The shape of ``tri-al.toml`` (docs/design.md §5.7)."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tri_al.config.schedule import Schedule
from tri_al.embeddings import DEFAULT_ENGINE, DEFAULT_MAX_TOKENS, DEFAULT_MODEL


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
    # The built front end (`npm run build` in web/). Default: web/dist in this checkout.
    web_dir: Path | None = None

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


class EmbeddingsConfig(_Section):
    """Trial vectors, made for new and changed trials in each update (``[embeddings]``).

    ``tri-al embeddings generate`` makes the rest, or all of them again after a change here.
    """

    enabled: bool = True
    engine: str = DEFAULT_ENGINE
    model: str = DEFAULT_MODEL
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=8, le=512)  # input the model reads
    float16: bool = True  # on a GPU; a CPU uses float32
    batch_size: int = Field(default=256, ge=1, le=4096)
    device: str | None = None  # cpu, mps or cuda; default: the best there is


LABEL_COLORS = ("blue", "orange", "teal", "amber", "pink", "green", "violet", "red")
"""Colours an annotation label can take; the front end draws them from its chart palette."""


class AnnotationLabel(_Section):
    """A class of terms the annotation task marks in trial text (``[[ai.annotation.labels]]``).

    The model reads the name, the description and the examples, so all three steer it.
    """

    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=300)
    examples: list[str] = Field(default_factory=list, max_length=8)
    color: str = ""  # one of LABEL_COLORS; empty: by the label's position

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("a label needs a name")
        return value

    @field_validator("examples")
    @classmethod
    def _examples(cls, value: list[str]) -> list[str]:
        return [example.strip() for example in value if example.strip()]

    @field_validator("color")
    @classmethod
    def _known_color(cls, value: str) -> str:
        if value and value not in LABEL_COLORS:
            raise ValueError(f"color must be one of {', '.join(LABEL_COLORS)}")
        return value


def _default_labels() -> list[AnnotationLabel]:
    return [
        AnnotationLabel(
            name="Condition",
            description="Diseases, disorders, syndromes and symptoms",
            examples=["Alzheimer's disease", "mild cognitive impairment", "agitation"],
            color="red",
        ),
        AnnotationLabel(
            name="Intervention",
            description="Drugs, biologics, devices, procedures and behavioral programs given "
            "in the study, including placebo",
            examples=["lecanemab", "placebo", "aerobic exercise"],
            color="blue",
        ),
        AnnotationLabel(
            name="Biomarker",
            description="Biological markers and how they are measured",
            examples=["amyloid PET", "plasma p-tau217", "APOE e4"],
            color="teal",
        ),
        AnnotationLabel(
            name="Assessment",
            description="Named scales, tests and questionnaires",
            examples=["MMSE", "CDR-SB", "ADAS-Cog"],
            color="violet",
        ),
    ]


class AnnotationConfig(_Section):
    """The annotation task (``[ai.annotation]``): its labels, and how text is cut up."""

    labels: list[AnnotationLabel] = Field(default_factory=_default_labels, max_length=12)
    chunk_chars: int = Field(default=900, ge=200, le=8000)  # each request's share of the text

    @field_validator("labels")
    @classmethod
    def _unique_names(cls, value: list[AnnotationLabel]) -> list[AnnotationLabel]:
        names = [label.name.casefold() for label in value]
        if len(set(names)) != len(names):
            raise ValueError("label names must differ")
        return value


class AiConfig(_Section):
    """The AI engine (``[ai]``): which model answers, and the tasks built on it.

    Settings edits from the app apply at once, without a restart (``tri_al.ai.AiService``).
    """

    enabled: bool = True
    # How models are reached: "openai" is any OpenAI-compatible server (LM Studio, Ollama,
    # llama.cpp, vLLM); plugins may add others (registry.add_model_backend).
    backend: str = "openai"
    server: str = "http://127.0.0.1:1234/v1"  # LM Studio's default; Ollama: :11434/v1
    model: str = ""  # empty: the first model the server has loaded
    timeout: float = Field(default=60, gt=0, le=600)  # seconds, per request
    parallel: int = Field(default=4, ge=1, le=32)  # requests at once, for one text
    annotation: AnnotationConfig = Field(default_factory=AnnotationConfig)

    @field_validator("server")
    @classmethod
    def _http_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("server must be an http:// or https:// URL")
        return value


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
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    plugins: dict[str, PluginSection] = Field(default_factory=dict)

    def plugin_enabled(self, name: str) -> bool:
        section = self.plugins.get(name)
        return section is None or section.enabled

    def plugin_settings(self, name: str) -> dict[str, Any]:
        section = self.plugins.get(name)
        return {} if section is None else section.settings
