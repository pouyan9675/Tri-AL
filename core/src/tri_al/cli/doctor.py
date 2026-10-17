"""``tri-al doctor``."""

import typer

from tri_al.doctor import Status, run_checks

_STYLES: dict[Status, str] = {"ok": "green", "warn": "yellow", "fail": "red"}


def doctor() -> None:
    """Check config, files, versions and plugins."""
    checks = run_checks()
    for check in checks:
        label = typer.style(f"{check.status:<4}", fg=_STYLES[check.status], bold=True)
        detail = check.detail.replace("\n", "\n      ")
        typer.echo(f"{label}  {check.name}: {detail}")
        if check.fix:
            typer.echo(f"      fix: {check.fix}")
    failed = sum(check.status == "fail" for check in checks)
    if failed:
        typer.echo(f"\n{failed} check{'s' if failed > 1 else ''} failed.", err=True)
        raise typer.Exit(1)
    typer.echo("\nAll checks passed.")
