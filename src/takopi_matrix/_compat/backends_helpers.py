"""Copied from takopi.backends_helpers - DEPRECATED."""

from __future__ import annotations

from takopi.api import SetupIssue


def install_issue(cmd: str, install_cmd: str | None) -> SetupIssue:
    if install_cmd:
        lines = (f"   [dim]$[/] {install_cmd}",)
    else:
        lines = ("   [dim]See engine setup docs for install instructions.[/]",)
    return SetupIssue(
        f"install {cmd}",
        lines,
    )
