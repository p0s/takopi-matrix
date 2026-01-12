"""Compatibility layer for takopi internals not yet in public API.

DEPRECATED: This module contains code copied from takopi internals.
These should migrate to takopi.api imports when available.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "takopi_matrix._compat contains copied takopi internals. "
    "These should be replaced with takopi.api imports when available.",
    DeprecationWarning,
    stacklevel=2,
)

from .logging import get_logger, bind_run_context, clear_context, suppress_logs
from .markdown import MarkdownFormatter, MarkdownParts, assemble_markdown_parts
from .progress import ProgressState, ProgressTracker
from .scheduler import ThreadJob, ThreadScheduler
from .config import ensure_table, read_config, write_config, HOME_CONFIG_PATH
from .settings import load_settings
from .paths import set_run_base_dir, reset_run_base_dir, relativize_path
from .commands import get_command, list_command_ids
from .ids import RESERVED_COMMAND_IDS
from .engines import list_backends
from .backends_helpers import install_issue

__all__ = [
    # logging
    "get_logger",
    "bind_run_context",
    "clear_context",
    "suppress_logs",
    # markdown
    "MarkdownFormatter",
    "MarkdownParts",
    "assemble_markdown_parts",
    # progress
    "ProgressState",
    "ProgressTracker",
    # scheduler
    "ThreadJob",
    "ThreadScheduler",
    # config
    "ensure_table",
    "read_config",
    "write_config",
    "HOME_CONFIG_PATH",
    # settings
    "load_settings",
    # paths
    "set_run_base_dir",
    "reset_run_base_dir",
    "relativize_path",
    # commands
    "get_command",
    "list_command_ids",
    # ids
    "RESERVED_COMMAND_IDS",
    # engines
    "list_backends",
    # backends_helpers
    "install_issue",
]
