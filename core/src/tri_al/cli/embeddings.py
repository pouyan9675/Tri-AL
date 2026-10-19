"""``tri-al embeddings``: make the trial vectors the configured model hasn't made yet."""

import time
from typing import Annotated

import typer

from tri_al.cli.data import DataDir, _as_job, _pipeline, duration
from tri_al.embeddings import EmbeddingError
from tri_al.pipeline import EmbeddingSummary, PipelineError, ProgressCallback

app = typer.Typer(help="Make and maintain the trial vectors ([embeddings] in tri-al.toml).")


@app.command("generate")
def generate(
    data_dir: DataDir = None,
    force: Annotated[
        bool, typer.Option("--force", help="Embed every trial again, not only the missing.")
    ] = False,
) -> None:
    """Embed the trials that have no vector from the configured model, newest first.

    Runs as a data job, so no install or update writes at the same time. Stopping it loses
    at most one batch; run it again to carry on.
    """
    pipeline = _pipeline(data_dir, workers=0)
    if pipeline.embedder is None:
        typer.echo("error: embeddings are off in tri-al.toml ([embeddings] enabled)", err=True)
        raise typer.Exit(1)
    started = time.monotonic()

    def run(progress: ProgressCallback) -> EmbeddingSummary:
        try:
            return pipeline.run_embedding_backfill(progress, force=force)
        except EmbeddingError as exc:
            raise PipelineError(str(exc)) from exc

    summary = _as_job(pipeline, "embeddings", {"force": force}, run)
    typer.echo(
        f"\nEmbedded {summary.trials:,} trials in {duration(time.monotonic() - started)} with "
        f"{summary.model} (data version {summary.data_version})."
    )
    if summary.skipped:
        typer.echo(f"{summary.skipped:,} trials changed meanwhile; their update embedded them.")
    for error in summary.stats_errors:
        typer.echo(f"stats: {error}", err=True)


__all__ = ["app", "generate"]
