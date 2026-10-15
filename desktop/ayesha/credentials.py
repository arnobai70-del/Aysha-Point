"""OANDA token handling. The token is a credential: it is only ever

- typed hidden by the owner (getpass) or read from stdin when stdin is not a terminal,
- stored in the Windows *user* environment (HKCU\\Environment) through the registry API, so it
  never appears as a command-line argument (no `setx <token>`), and never in the repository,
- read from the process environment, falling back to HKCU\\Environment on Windows,
- sent only in the HTTPS Authorization header to OANDA.

It is never printed, logged, written to the database, reports or artifacts. `redact()` scrubs it
from any text that could be shown.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable, Protocol

TOKEN_ENV = "AYESHA_OANDA_TOKEN"
# OANDA personal access tokens are 32 hex + "-" + 32 hex; accept a tolerant superset, never spaces.
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{19,199}$")


class Store(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsUserEnv:
    """HKCU\\Environment through winreg (no subprocess, no command-line arguments)."""

    def __init__(self) -> None:
        import winreg  # noqa: F401  (Windows only)

    def read(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                return str(v) if v else None
        except OSError:
            return None

    def write(self, name: str, value: str) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        _broadcast_env_change()

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass
        _broadcast_env_change()


def _broadcast_env_change() -> None:
    """Tell Explorer the environment changed, so new windows see it (same effect as setx)."""
    try:
        import ctypes

        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                                 SMTO_ABORTIFHUNG, 2000, None)
    except Exception:
        pass


def default_store() -> Store | None:
    if sys.platform != "win32":
        return None
    try:
        return WindowsUserEnv()
    except Exception:
        return None


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ""))


def get_token(env: dict[str, str] | None = None, store: Store | None | bool = True) -> str:
    """Process environment first, then (Windows) the user environment saved by `ayesha set-token`."""
    env = os.environ if env is None else env
    v = (env.get(TOKEN_ENV) or "").strip()
    if v:
        return v
    st = default_store() if store is True else (store or None)
    return ((st.read(TOKEN_ENV) if st else None) or "").strip()


def save_token(token: str, store: Store | None = None) -> None:
    token = token.strip()
    if not valid_token(token):
        raise ValueError("this does not look like an OANDA token (letters, digits and '-' only, 20+ characters)")
    st = store or default_store()
    if st is None:
        raise RuntimeError("saving the token is supported on Windows; elsewhere export AYESHA_OANDA_TOKEN yourself")
    st.write(TOKEN_ENV, token)
    os.environ[TOKEN_ENV] = token  # this process (and children it starts) can use it at once


def delete_token(store: Store | None = None) -> None:
    st = store or default_store()
    if st is not None:
        st.delete(TOKEN_ENV)
    os.environ.pop(TOKEN_ENV, None)


def read_hidden(prompt: str, stdin=None, getpass_fn: Callable[[str], str] | None = None) -> str:
    """Hidden prompt on a terminal; one line from stdin otherwise (scripted installs, CI)."""
    stdin = stdin or sys.stdin
    if stdin.isatty():
        import getpass

        return (getpass_fn or getpass.getpass)(prompt)
    print(prompt, flush=True)
    return stdin.readline().rstrip("\r\n")


def redact(text: str, token: str | None = None) -> str:
    """Remove the token (and anything token-shaped after 'Bearer') from text before it is shown."""
    token = token if token is not None else get_token(store=False)
    if token:
        text = text.replace(token, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_-]{8,}", r"\1***", text)
