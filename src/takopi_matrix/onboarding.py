from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import anyio
import httpx
import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary.constants import DEFAULT_QUESTION_PREFIX
from questionary.question import Question
from questionary.styles import merge_styles_default
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Public API imports from takopi
from takopi.api import (
    ConfigError,
    EngineBackend,
    SetupIssue,
    SetupResult,
)

# Direct takopi module imports
from takopi.backends_helpers import install_issue
from takopi.config import HOME_CONFIG_PATH, ensure_table, read_config, write_config
from takopi.engines import list_backends
from takopi.logging import suppress_logs
from takopi.settings import load_settings

import nio


def _check_libolm_available() -> bool:
    """Check if libolm is available (E2EE support works)."""
    try:
        from nio.crypto import Olm  # noqa: F401

        return True
    except ImportError:
        return False


def _libolm_install_issue() -> SetupIssue:
    """Create setup issue for missing libolm."""
    import platform

    system = platform.system().lower()

    if system == "darwin":
        install_cmd = "brew install libolm"
    elif system == "linux":
        # Try to detect distro
        try:
            with open("/etc/os-release") as f:
                os_release = f.read().lower()
        except FileNotFoundError:
            os_release = ""

        if "ubuntu" in os_release or "debian" in os_release:
            install_cmd = "sudo apt-get install libolm-dev"
        elif "fedora" in os_release or "rhel" in os_release or "centos" in os_release:
            install_cmd = "sudo dnf install libolm-devel"
        elif "arch" in os_release:
            install_cmd = "sudo pacman -S libolm"
        elif "opensuse" in os_release or "suse" in os_release:
            install_cmd = "sudo zypper install libolm-devel"
        else:
            install_cmd = "Install libolm-dev (or libolm-devel) for your distro"
    elif system == "windows":
        install_cmd = "Build libolm from source (see docs)"
    else:
        install_cmd = "Install libolm for your platform"

    return SetupIssue(
        "install libolm (E2EE dependency)",
        (f"   {install_cmd}",),
    )


@dataclass(frozen=True, slots=True)
class MatrixUserInfo:
    user_id: str
    display_name: str | None
    device_id: str | None


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


_CREATE_CONFIG_TITLE = "create a config"
_CONFIGURE_MATRIX_TITLE = "configure matrix"


def config_issue(path: Path, *, title: str) -> SetupIssue:
    return SetupIssue(title, (f"   {_display_path(path)}",))


def _check_matrix_config(settings: Any, config_path: Path) -> list[SetupIssue]:
    """Validate Matrix configuration."""
    issues: list[SetupIssue] = []

    if settings.transport != "matrix":
        return issues

    transport_config = getattr(settings, "transports", {}).get("matrix", {})

    if not transport_config.get("homeserver"):
        issues.append(config_issue(config_path, title=_CONFIGURE_MATRIX_TITLE))
        return issues

    if not transport_config.get("user_id"):
        issues.append(config_issue(config_path, title=_CONFIGURE_MATRIX_TITLE))
        return issues

    if not transport_config.get("access_token") and not transport_config.get(
        "password"
    ):
        issues.append(config_issue(config_path, title=_CONFIGURE_MATRIX_TITLE))
        return issues

    room_ids = transport_config.get("room_ids")
    if not room_ids or not isinstance(room_ids, list):
        issues.append(config_issue(config_path, title=_CONFIGURE_MATRIX_TITLE))
        return issues

    return issues


def check_setup(
    backend: EngineBackend,
    *,
    transport_override: str | None = None,
) -> SetupResult:
    issues: list[SetupIssue] = []
    config_path = HOME_CONFIG_PATH
    cmd = backend.cli_cmd or backend.id
    backend_issues: list[SetupIssue] = []

    if shutil.which(cmd) is None:
        backend_issues.append(install_issue(cmd, backend.install_cmd))

    if not _check_libolm_available():
        issues.append(_libolm_install_issue())

    try:
        settings, config_path = load_settings()
        if transport_override:
            settings = settings.model_copy(update={"transport": transport_override})

        matrix_issues = _check_matrix_config(settings, config_path)
        if matrix_issues:
            issues.extend(matrix_issues)

    except ConfigError:
        issues.extend(backend_issues)
        title = (
            _CONFIGURE_MATRIX_TITLE
            if config_path.exists() and config_path.is_file()
            else _CREATE_CONFIG_TITLE
        )
        issues.append(config_issue(config_path, title=title))
        return SetupResult(issues=issues, config_path=config_path)

    issues.extend(backend_issues)
    return SetupResult(issues=issues, config_path=config_path)


def _mask_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 12:
        return "*" * len(token)
    return f"{token[:9]}...{token[-5:]}"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_config(
    homeserver: str,
    user_id: str,
    access_token: str,
    room_ids: list[str],
    default_engine: str | None,
    *,
    send_startup_message: bool = True,
) -> str:
    lines: list[str] = []
    if default_engine:
        lines.append(f'default_engine = "{_toml_escape(default_engine)}"')
        lines.append("")
    lines.append('transport = "matrix"')
    lines.append("")
    lines.append("[transports.matrix]")
    lines.append(f'homeserver = "{_toml_escape(homeserver)}"')
    lines.append(f'user_id = "{_toml_escape(user_id)}"')
    lines.append(f'access_token = "{_toml_escape(access_token)}"')
    lines.append(f"room_ids = {room_ids!r}")
    if not send_startup_message:
        lines.append("send_startup_message = false")
    return "\n".join(lines) + "\n"


async def _discover_homeserver(server_name: str) -> str:
    """
    Discover homeserver URL using .well-known.

    Tries https://{server_name}/.well-known/matrix/client first,
    falls back to https://{server_name} if discovery fails.
    """
    if server_name.startswith("http://") or server_name.startswith("https://"):
        return server_name.rstrip("/")

    well_known_url = f"https://{server_name}/.well-known/matrix/client"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(well_known_url)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    hs = data.get("m.homeserver", {})
                    if isinstance(hs, dict):
                        base_url = hs.get("base_url")
                        if isinstance(base_url, str) and base_url:
                            return base_url.rstrip("/")
        except Exception:
            pass

    return f"https://{server_name}"


async def _test_login(
    homeserver: str,
    user_id: str,
    password: str,
) -> tuple[bool, str | None, str | None, str | None]:
    """
    Test login credentials.

    Returns (success, access_token, device_id, error_message).
    """
    client = nio.AsyncClient(homeserver, user_id)
    try:
        response = await client.login(password=password, device_name="Takopi")
        if isinstance(response, nio.LoginResponse):
            return True, response.access_token, response.device_id, None
        # LoginError or other error response
        error_msg = getattr(response, "message", None) or str(response)
        return False, None, None, error_msg
    except Exception as exc:
        return False, None, None, str(exc)
    finally:
        await client.close()


async def _test_token(
    homeserver: str,
    user_id: str,
    access_token: str,
) -> bool:
    """Test if access token is valid."""
    client = nio.AsyncClient(homeserver, user_id)
    client.access_token = access_token
    client.user_id = user_id

    try:
        response = await client.sync(timeout=5000)
        return isinstance(response, nio.SyncResponse)
    except Exception:
        return False
    finally:
        await client.close()


@dataclass(frozen=True, slots=True)
class RoomInvite:
    room_id: str
    inviter: str | None
    room_name: str | None


async def _fetch_room_invites(
    homeserver: str,
    user_id: str,
    access_token: str,
) -> list[RoomInvite]:
    """Fetch pending room invites."""
    client = nio.AsyncClient(homeserver, user_id)
    client.access_token = access_token
    client.user_id = user_id

    try:
        response = await client.sync(timeout=5000)
        if not isinstance(response, nio.SyncResponse):
            return []

        invites: list[RoomInvite] = []
        for room_id, invite_info in response.rooms.invite.items():
            inviter: str | None = None
            room_name: str | None = None

            for event in invite_info.invite_state:
                if hasattr(event, "sender"):
                    inviter = event.sender
                if hasattr(event, "name"):
                    room_name = event.name

            invites.append(RoomInvite(room_id, inviter, room_name))

        return invites
    except Exception:
        return []
    finally:
        await client.close()


async def _accept_room_invite(
    homeserver: str,
    user_id: str,
    access_token: str,
    room_id: str,
) -> bool:
    """Accept a room invite."""
    client = nio.AsyncClient(homeserver, user_id)
    client.access_token = access_token
    client.user_id = user_id

    try:
        response = await client.join(room_id)
        return isinstance(response, nio.JoinResponse)
    except Exception:
        return False
    finally:
        await client.close()


async def _wait_for_room(
    homeserver: str,
    user_id: str,
    access_token: str,
) -> str | None:
    """Wait for a message in any room and return the room_id."""
    client = nio.AsyncClient(homeserver, user_id)
    client.access_token = access_token
    client.user_id = user_id

    try:
        since: str | None = None
        initial = await client.sync(timeout=0)
        if isinstance(initial, nio.SyncResponse):
            since = initial.next_batch

        while True:
            response = await client.sync(timeout=30000, since=since)
            if not isinstance(response, nio.SyncResponse):
                await anyio.sleep(1)
                continue

            since = response.next_batch

            for room_id, room_info in response.rooms.join.items():
                for event in room_info.timeline.events:
                    if hasattr(event, "sender") and event.sender != user_id:
                        return room_id

    except Exception:
        return None
    finally:
        await client.close()


async def _send_confirmation(
    homeserver: str,
    user_id: str,
    access_token: str,
    room_id: str,
) -> bool:
    """Send confirmation message to room."""
    client = nio.AsyncClient(homeserver, user_id)
    client.access_token = access_token
    client.user_id = user_id

    try:
        response = await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": "takopi is configured and ready.",
            },
        )
        return isinstance(response, nio.RoomSendResponse)
    except Exception:
        return False
    finally:
        await client.close()


def _render_engine_table(console: Console) -> list[tuple[str, bool, str | None]]:
    backends = list_backends()
    rows: list[tuple[str, bool, str | None]] = []
    table = Table(show_header=True, header_style="bold", box=box.SIMPLE)
    table.add_column("agent")
    table.add_column("status")
    table.add_column("install command")
    for backend in backends:
        cmd = backend.cli_cmd or backend.id
        installed = shutil.which(cmd) is not None
        status = (
            "[green]\u2713 installed[/]" if installed else "[dim]\u2717 not found[/]"
        )
        rows.append((backend.id, installed, backend.install_cmd))
        table.add_row(
            backend.id,
            status,
            "" if installed else (backend.install_cmd or "-"),
        )
    console.print(table)
    return rows


@contextmanager
def _suppress_logging():
    with suppress_logs():
        yield


def _confirm(message: str, *, default: bool = True) -> bool | None:
    merged_style = merge_styles_default([None])
    status = {"answer": None, "complete": False}

    def get_prompt_tokens():
        tokens = [
            ("class:qmark", DEFAULT_QUESTION_PREFIX),
            ("class:question", f" {message} "),
        ]
        if not status["complete"]:
            tokens.append(("class:instruction", "(yes/no) "))
        if status["answer"] is not None:
            tokens.append(("class:answer", "yes" if status["answer"] else "no"))
        return to_formatted_text(tokens)

    def exit_with_result(event):
        status["complete"] = True
        event.app.exit(result=status["answer"])

    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add("n")
    @bindings.add("N")
    def key_n(event):
        status["answer"] = False
        exit_with_result(event)

    @bindings.add("y")
    @bindings.add("Y")
    def key_y(event):
        status["answer"] = True
        exit_with_result(event)

    @bindings.add(Keys.ControlH)
    def key_backspace(event):
        status["answer"] = None

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event):
        if status["answer"] is None:
            status["answer"] = default
        exit_with_result(event)

    @bindings.add(Keys.Any)
    def other(event):
        _ = event

    question = Question(
        PromptSession(get_prompt_tokens, key_bindings=bindings, style=merged_style).app
    )
    return question.ask()


def _prompt_homeserver(console: Console) -> str | None:
    """Prompt for Matrix homeserver."""
    while True:
        server = questionary.text("enter your matrix server (e.g., matrix.org):").ask()
        if server is None:
            return None
        server = server.strip()
        if not server:
            console.print("  server cannot be empty")
            continue

        console.print("  discovering homeserver...")
        homeserver = anyio.run(_discover_homeserver, server)
        console.print(f"  found: {homeserver}")
        return homeserver


def _prompt_credentials(
    console: Console,
    homeserver: str,
) -> tuple[str, str, str | None] | None:
    """
    Prompt for Matrix credentials.

    Returns (user_id, access_token, device_id) or None.
    """
    user_id = questionary.text("enter your user ID (e.g., @bot:matrix.org):").ask()
    if user_id is None:
        return None
    user_id = user_id.strip()
    if not user_id:
        console.print("  user ID cannot be empty")
        return None

    if not user_id.startswith("@"):
        domain = homeserver.replace("https://", "").replace("http://", "").split("/")[0]
        user_id = f"@{user_id}:{domain}"
        console.print(f"  using: {user_id}")

    auth_method = questionary.select(
        "authentication method:",
        choices=["access token (recommended)", "password"],
    ).ask()
    if auth_method is None:
        return None

    if auth_method == "password":
        password = questionary.password("enter password:").ask()
        if password is None:
            return None

        console.print("  logging in...")
        # Cast to override anyio.run's incorrect type stub (returns None instead of func return type)
        result = cast(
            tuple[bool, str | None, str | None, str | None],
            anyio.run(_test_login, homeserver, user_id, password),
        )
        ok, token, device_id, error_msg = result
        if not ok or not token:
            if error_msg:
                console.print(f"  login failed: {error_msg}")
            else:
                console.print("  login failed")
            retry = _confirm("try again?", default=True)
            if retry:
                return _prompt_credentials(console, homeserver)
            return None

        console.print(f"  logged in (device: {device_id})")
        return user_id, token, device_id

    token = questionary.password("paste access token:").ask()
    if token is None:
        return None
    token = token.strip()

    console.print("  validating...")
    ok = anyio.run(_test_token, homeserver, user_id, token)
    if not ok:
        console.print("  token validation failed")
        retry = _confirm("try again?", default=True)
        if retry:
            return _prompt_credentials(console, homeserver)
        return None

    console.print("  token valid")
    return user_id, token, None


def interactive_setup(*, force: bool) -> bool:
    console = Console()
    config_path = HOME_CONFIG_PATH

    if config_path.exists() and not force:
        console.print(
            f"config already exists at {_display_path(config_path)}. "
            "use --onboard to reconfigure."
        )
        return True

    if config_path.exists() and force:
        overwrite = _confirm(
            f"update existing config at {_display_path(config_path)}?",
            default=False,
        )
        if not overwrite:
            return False

    with _suppress_logging():
        panel = Panel(
            "let's set up your matrix bot.",
            title="welcome to takopi!",
            border_style="yellow",
            padding=(1, 2),
            expand=False,
        )
        console.print(panel)

        console.print("step 1: matrix homeserver\n")
        homeserver = _prompt_homeserver(console)
        if homeserver is None:
            return False

        console.print("\nstep 2: authentication\n")
        creds = _prompt_credentials(console, homeserver)
        if creds is None:
            return False
        user_id, access_token, device_id = creds

        console.print("\nstep 3: room selection\n")
        console.print("  invite your bot to a room, then accept the invite here")

        room_ids: list[str] = []

        while True:
            console.print("  fetching room invites...")
            invites = cast(
                list[RoomInvite],
                anyio.run(_fetch_room_invites, homeserver, user_id, access_token),
            )

            if not invites:
                console.print("  no pending invites found")
                action = questionary.select(
                    "what would you like to do?",
                    choices=[
                        "refresh invites",
                        "enter room ID manually",
                        "done selecting rooms" if room_ids else "skip (no rooms)",
                    ],
                ).ask()

                if action is None:
                    return False

                if action == "refresh invites":
                    continue

                if action == "enter room ID manually":
                    room_id = questionary.text(
                        "enter room ID (e.g., !abc123:matrix.org):"
                    ).ask()
                    if room_id and room_id.strip():
                        room_ids.append(room_id.strip())
                        console.print(f"  added: {room_id.strip()}")
                    continue

                # done or skip
                break

            # Build choices from invites
            choices: list[str] = []
            for invite in invites:
                label = invite.room_id
                if invite.room_name:
                    label = f"{invite.room_name} ({invite.room_id})"
                if invite.inviter:
                    label += f" from {invite.inviter}"
                choices.append(label)
            choices.append("refresh invites")
            choices.append("enter room ID manually")
            if room_ids:
                choices.append("done selecting rooms")

            selected = questionary.select(
                "select a room invite to accept:",
                choices=choices,
            ).ask()

            if selected is None:
                return False

            if selected == "refresh invites":
                continue

            if selected == "enter room ID manually":
                room_id = questionary.text(
                    "enter room ID (e.g., !abc123:matrix.org):"
                ).ask()
                if room_id and room_id.strip():
                    room_ids.append(room_id.strip())
                    console.print(f"  added: {room_id.strip()}")
                continue

            if selected == "done selecting rooms":
                break

            # Find the selected invite
            selected_invite: RoomInvite | None = None
            for invite in invites:
                label = invite.room_id
                if invite.room_name:
                    label = f"{invite.room_name} ({invite.room_id})"
                if invite.inviter:
                    label += f" from {invite.inviter}"
                if label == selected:
                    selected_invite = invite
                    break

            if selected_invite is None:
                continue

            console.print(f"  accepting invite to {selected_invite.room_id}...")
            accepted = anyio.run(
                _accept_room_invite,
                homeserver,
                user_id,
                access_token,
                selected_invite.room_id,
            )

            if accepted:
                room_ids.append(selected_invite.room_id)
                console.print(f"  [green]joined {selected_invite.room_id}[/]")
            else:
                console.print(f"  [red]failed to join {selected_invite.room_id}[/]")

            add_more = _confirm("add more rooms?", default=False)
            if not add_more:
                break

        if not room_ids:
            console.print("  [yellow]warning: no rooms selected[/]")
            proceed = _confirm("continue without rooms?", default=False)
            if not proceed:
                return False

        if room_ids:
            sent = anyio.run(
                _send_confirmation, homeserver, user_id, access_token, room_ids[0]
            )
            if sent:
                console.print("  sent confirmation message")
            else:
                console.print("  could not send confirmation message")

        console.print("\nstep 4: agent cli tools")
        rows = _render_engine_table(console)
        installed_ids = [engine_id for engine_id, installed, _ in rows if installed]

        default_engine: str | None = None
        if installed_ids:
            default_engine = questionary.select(
                "choose default agent:",
                choices=installed_ids,
            ).ask()
            if default_engine is None:
                return False
        else:
            console.print("no agents found on PATH. install one to continue.")
            save_anyway = _confirm("save config anyway?", default=False)
            if not save_anyway:
                return False

        console.print("\nstep 4.5: encryption support")

        # Check libolm availability (required for E2EE)
        if not _check_libolm_available():
            console.print("  [red]libolm not detected[/]")
            console.print("  E2EE requires the libolm system library")
            issue = _libolm_install_issue()
            for hint in issue.hints:
                console.print(f"  {hint}")
            console.print("\n  after installation, restart setup with --onboard")
            return False
        else:
            console.print("  [green]E2EE support detected[/] ✓")

        console.print("\nstep 4.6: startup message")
        console.print("  takopi can send a status message when it starts")
        send_startup_message = _confirm(
            "send startup message when bot starts?",
            default=True,
        )
        if send_startup_message is None:
            return False

        config_preview = _render_config(
            homeserver,
            user_id,
            _mask_token(access_token),
            room_ids,
            default_engine,
            send_startup_message=send_startup_message,
        ).rstrip()
        console.print("\nstep 5: save configuration\n")
        console.print(f"  {_display_path(config_path)}\n")
        for line in config_preview.splitlines():
            console.print(f"  {line}")
        console.print("")

        save = _confirm(
            f"save this config to {_display_path(config_path)}?",
            default=True,
        )
        if not save:
            return False

        raw_config: dict[str, Any] = {}
        if config_path.exists():
            try:
                raw_config = read_config(config_path)
            except ConfigError as exc:
                console.print(f"[yellow]warning:[/] config is malformed: {exc}")
                backup = config_path.with_suffix(".toml.bak")
                try:
                    shutil.copyfile(config_path, backup)
                except OSError as copy_exc:
                    console.print(
                        f"[yellow]warning:[/] failed to back up config: {copy_exc}"
                    )
                else:
                    console.print(f"  backed up to {_display_path(backup)}")
                raw_config = {}

        merged = dict(raw_config)
        if default_engine is not None:
            merged["default_engine"] = default_engine
        merged["transport"] = "matrix"

        transports = ensure_table(merged, "transports", config_path=config_path)
        matrix = ensure_table(
            transports,
            "matrix",
            config_path=config_path,
            label="transports.matrix",
        )
        matrix["homeserver"] = homeserver
        matrix["user_id"] = user_id
        matrix["access_token"] = access_token
        matrix["room_ids"] = room_ids
        matrix["send_startup_message"] = send_startup_message
        if device_id:
            matrix["device_id"] = device_id

        merged.pop("bot_token", None)
        merged.pop("chat_id", None)

        write_config(merged, config_path)
        console.print(f"  config saved to {_display_path(config_path)}")

        done_panel = Panel(
            "setup complete. starting takopi...",
            border_style="green",
            padding=(1, 2),
            expand=False,
        )
        console.print("\n")
        console.print(done_panel)
        return True
