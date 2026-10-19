"""``tri-al install`` and ``tri-al update``: the pipeline, with plain progress output.

Milestone 6 polishes the install experience; this prints a line per stage and an update
every few seconds.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Protocol

import typer

from tri_al.config import ConfigError, load_config
from tri_al.jobs import JobCancelled, JobConflict, JobProgress, JobQueue
from tri_al.pipeline import (
    FetchError,
    Pipeline,
    PipelineError,
    Progress,
    ProgressCallback,
    RenormalizeSummary,
    RunSummary,
)
from tri_al.plugins import PluginError, load_plugins
from tri_al.storage import StorageError, open_app_db

DataDir = Annotated[
    Path | None,
    typer.Option(
        "--data-dir",
        file_okay=False,
        help="Where the databases and downloads go. Default: data.dir from tri-al.toml.",
    ),
]


def install(
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from-file",
            exists=True,
            dir_okay=False,
            help="Read this ctg-studies.json.zip instead of downloading it.",
        ),
    ] = None,
    data_dir: DataDir = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Rebuild an existing database; its change log starts over."),
    ] = False,
    workers: Annotated[
        int | None,
        typer.Option(min=0, help="Processes that normalize trials (0: none). Default: CPUs - 1."),
    ] = None,
) -> None:
    """Download every trial and build the database."""
    pipeline = _pipeline(data_dir, workers)
    started = time.monotonic()
    payload = {"from_file": None if from_file is None else str(from_file), "force": force}
    summary = _as_job(
        pipeline,
        "install",
        payload,
        lambda progress: pipeline.run_install(progress, from_file=from_file, force=force),
    )
    typer.echo(
        f"\nInstalled into {pipeline.trials_db} in {duration(time.monotonic() - started)} "
        f"(data version {summary.data_version})."
    )
    _report(summary)


def update(data_dir: DataDir = None) -> None:
    """Fetch the trials changed since the last update."""
    pipeline = _pipeline(data_dir, workers=0)
    started = time.monotonic()
    summary = _as_job(pipeline, "update", {}, pipeline.run_update)
    typer.echo(
        f"\nUpdated {pipeline.trials_db} in {duration(time.monotonic() - started)} "
        f"(data version {summary.data_version})."
    )
    _report(summary)


def stats(data_dir: DataDir = None) -> None:
    """Recompute the dashboard's stats and derived tables, such as the cluster map, now.

    For after changing a plugin's settings: the data stays as it is, the data version goes
    up and the dashboard fetches the new results.
    """
    pipeline = _pipeline(data_dir, workers=0)
    started = time.monotonic()
    summary = _as_job(pipeline, "stats", {}, pipeline.run_stats)
    typer.echo(
        f"\nRecomputed the stats of {pipeline.trials_db} in "
        f"{duration(time.monotonic() - started)} (data version {summary.data_version})."
    )
    for error in summary.stats_errors:
        typer.echo(f"stats: {error}", err=True)


def renormalize(data_dir: DataDir = None) -> None:
    """Read every stored trial again from its raw document, with today's source plugins.

    For after a source plugin learns to read more of its documents, such as arms and
    design: trials keep their ids, change log and vectors, and only what changed is
    written. Stopping keeps the batches done; run it again to carry on.
    """
    pipeline = _pipeline(data_dir, workers=0)
    started = time.monotonic()
    summary: RenormalizeSummary = _as_job(pipeline, "renormalize", {}, pipeline.run_renormalize)
    typer.echo(
        f"\nRenormalized {summary.trials:,} trials in {duration(time.monotonic() - started)} "
        f"(data version {summary.data_version}): {summary.rewritten:,} rewritten in place, "
        f"{summary.replaced:,} replaced, {summary.unchanged:,} unchanged, "
        f"{summary.skipped:,} skipped, {summary.failed:,} failed."
    )
    for failure in summary.failures[:5]:
        typer.echo(f"  {failure}", err=True)
    if summary.embedding_error:
        typer.echo(
            f"warning: embedding replaced trials failed: {summary.embedding_error}", err=True
        )
    for error in summary.stats_errors:
        typer.echo(f"stats: {error}", err=True)


class ProgressPrinter:
    """Prints a line when a stage starts, then at most one every ``interval`` seconds.

    A stage's last report is printed when the next stage starts, so its final count shows.
    """

    def __init__(
        self,
        interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        echo: Callable[[str], object] = typer.echo,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._echo = echo
        self._stage: str | None = None
        self._last = 0.0
        self._unprinted: Progress | None = None

    def __call__(self, progress: Progress) -> None:
        now = self._clock()
        if progress.stage != self._stage and self._unprinted is not None:
            self._echo(describe(self._unprinted))
        if progress.stage != self._stage or now - self._last >= self._interval:
            self._stage, self._last, self._unprinted = progress.stage, now, None
            self._echo(describe(progress))
        else:
            self._unprinted = progress


def describe(progress: Progress) -> str:
    """``progress`` as one line, such as ``load: 5,000 of 607,349 trials (1%)``."""
    done, total = progress.done, progress.total
    if progress.unit == "bytes":
        amount = f"{done / 1e6:,.0f} MB" + (f" of {total / 1e6:,.0f} MB" if total else "")
    elif done or total:
        amount = f"{done:,}" + (f" of {total:,}" if total else "")
        amount += f" {progress.unit}" if progress.unit else ""
        amount += f" ({done / total:.0%})" if total else ""
    else:
        amount = ""
    return ": ".join(part for part in (progress.stage, amount, progress.message) if part)


def duration(seconds: float) -> str:
    """``seconds`` as ``1h02m``, ``4m05s`` or ``12.3s``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _pipeline(data_dir: Path | None, workers: int | None) -> Pipeline:
    try:
        config = load_config()
        plugins = load_plugins(config)
    except (ConfigError, PluginError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    return Pipeline.from_plugins(config, plugins, data_dir=data_dir, workers=workers)


class _Result(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


def _as_job[R: _Result](
    pipeline: Pipeline,
    job_type: str,
    payload: dict[str, Any],
    action: Callable[[ProgressCallback], R],
) -> R:
    """Run ``action`` as a job in ``app.db``, so the server shows it and waits for it.

    Only one data job (install, update or embedding backfill) runs at a time, whichever
    process starts it.
    """
    pipeline.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        engine = open_app_db(
            pipeline.app_db,
            extensions=pipeline.extensions,
            plugin_migrations=pipeline.app_migrations,
        )
    except StorageError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    queue = JobQueue(engine)
    try:
        try:
            job = queue.start(job_type, payload, origin="cli")
        except JobConflict as exc:
            typer.echo(f"error: {exc}; wait for it to finish, or cancel it", err=True)
            raise typer.Exit(1) from None
        try:
            with JobProgress(queue, job.id, also=ProgressPrinter()) as progress:
                summary = action(progress)
        except JobCancelled:
            queue.cancelled(job.id)
            typer.echo("\ncancelled; nothing was changed", err=True)
            raise typer.Exit(1) from None
        except (PipelineError, StorageError, FetchError) as exc:
            queue.fail(job.id, str(exc))
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            queue.fail(job.id, "interrupted")
            typer.echo("\ninterrupted; run the same command again to carry on", err=True)
            raise typer.Exit(130) from None
        except BaseException as exc:
            queue.fail(job.id, str(exc) or type(exc).__name__)
            raise
        queue.finish(job.id, summary.as_dict())
        return summary
    finally:
        engine.dispose()


def _report(summary: RunSummary) -> None:
    for source, counts in summary.sources.items():
        typer.echo(
            f"  {source}: {counts.fetched:,} fetched, {counts.new:,} new, "
            f"{counts.updated:,} updated, {counts.unchanged:,} unchanged, "
            f"{counts.failed:,} failed"
        )
    stages = ", ".join(f"{stage} {duration(seconds)}" for stage, seconds in summary.stages.items())
    typer.echo(f"  stages: {stages}")
    if summary.failures:
        typer.echo(f"\n{summary.failed:,} studies couldn't be read; the first few:", err=True)
        for failure in summary.failures[:5]:
            typer.echo(f"  {failure}", err=True)
    for error in summary.handler_errors:
        typer.echo(f"warning: {error}", err=True)
    for error in summary.stats_errors:
        typer.echo(f"warning: a chart couldn't be precomputed: {error}", err=True)
