# takopi-matrix

Matrix transport backend for [Takopi](https://github.com/banteg/takopi).

Extracted from the main takopi repository as a standalone plugin.

## Installation

```bash
pip install takopi-matrix
```

For end-to-end encryption support:

```bash
pip install takopi-matrix[e2ee]
```

## Configuration

After installation, run the setup wizard:

```bash
takopi setup matrix
```

Or manually configure in `~/.takopi/takopi.toml`:

```toml
transport = "matrix"

[transports.matrix]
homeserver = "https://matrix.example.org"
user_id = "@bot:example.org"
access_token = "your_access_token"
room_ids = ["!roomid:example.org"]
```

## Features

- Matrix protocol support via matrix-nio
- Optional end-to-end encryption (E2EE)
- Voice message transcription (via OpenAI)
- File download support
- Interactive onboarding wizard

## Non-Public API Notice

This plugin uses some internal takopi APIs that are not yet part of the public `takopi.api` module. These are copied into `takopi_matrix._compat` and marked as deprecated. They include:

- Logging utilities (`get_logger`, `bind_run_context`, `clear_context`, `suppress_logs`)
- Markdown formatting (`MarkdownFormatter`, `MarkdownParts`, `assemble_markdown_parts`)
- Progress tracking (`ProgressState`, `ProgressTracker`)
- Thread scheduling (`ThreadJob`, `ThreadScheduler`)
- Configuration helpers (`ensure_table`, `read_config`, `write_config`, `HOME_CONFIG_PATH`)
- Settings loading (`load_settings`)
- Path utilities (`set_run_base_dir`, `reset_run_base_dir`)
- Command discovery (`get_command`, `list_command_ids`, `RESERVED_COMMAND_IDS`)
- Engine discovery (`list_backends`, `install_issue`)

Future versions should migrate these to the official public API when available.

## License

MIT
