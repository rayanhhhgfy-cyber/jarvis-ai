# ====================================================================
# JARVIS OMEGA — Cross-platform Command Interpreter Tests
# ====================================================================
"""
Verifies the command interpreter emits native commands for Windows, Linux,
and macOS while keeping detection logic shared across platforms.
"""

import pytest

from backend.services.command_interpreter import CommandInterpreter


@pytest.fixture
def win():
    return CommandInterpreter(os_name="Windows")


@pytest.fixture
def linux():
    return CommandInterpreter(os_name="Linux")


@pytest.fixture
def mac():
    return CommandInterpreter(os_name="Darwin")


def _one(result):
    """Unwrap the single (description, command) tuple from interpret()."""
    assert result is not None, "expected a command to be interpreted"
    assert len(result) == 1
    return result[0]


def test_unknown_os_falls_back_to_linux():
    interp = CommandInterpreter(os_name="Plan9")
    assert interp.is_linux is True
    assert interp.is_windows is False


def test_open_app_is_os_specific(win, linux, mac):
    _, w = _one(win.interpret("open calculator"))
    _, l = _one(linux.interpret("open calculator"))
    _, m = _one(mac.interpret("open calculator"))
    assert w == "start calc"
    assert l == "nohup gnome-calculator >/dev/null 2>&1 &"
    assert m == "open -a Calculator"


def test_open_browser_is_os_specific(win, linux, mac):
    assert _one(win.interpret("open chrome"))[1] == "start chrome"
    assert _one(linux.interpret("open chrome"))[1] == "nohup google-chrome >/dev/null 2>&1 &"
    assert _one(mac.interpret("open chrome"))[1] == "open -a 'Google Chrome'"


def test_create_folder(win, linux, mac):
    assert _one(win.interpret("create a folder called demo"))[1] == 'mkdir "demo"'
    assert _one(linux.interpret("create a folder called demo"))[1] == 'mkdir -p "demo"'
    assert _one(mac.interpret("create a folder called demo"))[1] == 'mkdir -p "demo"'


def test_list_files(win, linux):
    assert _one(win.interpret("list the files in projects"))[1] == 'dir "projects"'
    assert _one(linux.interpret("list the files in projects"))[1] == 'ls -la "projects"'


def test_system_info(win, linux, mac):
    assert "systeminfo" in _one(win.interpret("what is my system info"))[1]
    assert "uname -a" in _one(linux.interpret("what is my system info"))[1]
    assert "sw_vers" in _one(mac.interpret("what is my system info"))[1]


def test_whoami_is_universal(win, linux, mac):
    for interp in (win, linux, mac):
        assert _one(interp.interpret("check my username"))[1] == "whoami"


def test_disk_usage(win, linux):
    assert "wmic" in _one(win.interpret("how much disk space"))[1]
    assert _one(linux.interpret("how much disk space"))[1] == "df -h"


def test_kill_process(win, linux):
    assert _one(win.interpret("close chrome"))[1] == "taskkill /IM chrome.exe /F"
    assert _one(linux.interpret("close chrome"))[1] == 'pkill -i -f "chrome"'


def test_shutdown_is_os_specific(win, linux, mac):
    assert "shutdown /s" in _one(win.interpret("shut down the computer"))[1]
    assert "shutdown -h" in _one(linux.interpret("shut down the computer"))[1]
    assert "System Events" in _one(mac.interpret("shut down the computer"))[1]


def test_lock_screen(win, linux, mac):
    assert "LockWorkStation" in _one(win.interpret("lock the computer"))[1]
    assert "lock-session" in _one(linux.interpret("lock the computer"))[1]
    assert "displaysleepnow" in _one(mac.interpret("lock the computer"))[1]


def test_ping(win, linux):
    assert _one(win.interpret("ping google.com"))[1] == "ping google.com -n 4"
    assert _one(linux.interpret("ping google.com"))[1] == "ping -c 4 google.com"


def test_open_url_is_os_specific(win, linux, mac):
    assert _one(win.interpret("open github"))[1] == 'start "" "https://github.com"'
    assert _one(linux.interpret("open github"))[1] == 'xdg-open "https://github.com"'
    assert _one(mac.interpret("open github"))[1] == 'open "https://github.com"'


def test_youtube_search_uses_native_opener(win, linux):
    _, w = _one(win.interpret("search for lofi beats on youtube"))
    _, l = _one(linux.interpret("search for lofi beats on youtube"))
    assert w.startswith('start "" "https://www.youtube.com/results?search_query=lofi+beats"')
    assert l == 'xdg-open "https://www.youtube.com/results?search_query=lofi+beats"'


def test_volume_control(win, linux, mac):
    assert "SendKeys" in _one(win.interpret("turn the volume up"))[1]
    assert _one(linux.interpret("turn the volume up"))[1] == "pactl set-sink-volume @DEFAULT_SINK@ +10%"
    assert "output volume" in _one(mac.interpret("turn the volume up"))[1]


def test_no_match_returns_none(linux):
    assert linux.interpret("what is the meaning of life") is None
