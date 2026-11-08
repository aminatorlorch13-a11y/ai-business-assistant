from pathlib import Path

import pytest

from app.forge.terminal import ForgeVirtualTerminal


@pytest.fixture
def terminal_workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def answer():\n    return 42\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "# Demo project\nAmination Forge workspace\n", encoding="utf-8"
    )
    return tmp_path


def test_help_lists_supported_commands(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute("help")
    assert result.ok
    assert "toolchain <language>" in result.output
    assert "arbitrary command" in result.output


def test_pwd_and_cd_are_workspace_relative(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    assert terminal.execute("pwd").output == "."
    assert terminal.execute("cd src").ok
    assert terminal.execute("pwd").output == "src"
    assert "main.py" in terminal.execute("ls").output


def test_cat_reads_workspace_file(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute("cat README.md")
    assert result.ok
    assert "Amination Forge workspace" in result.output


def test_grep_searches_literal_text(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute(
        'grep "return 42" src/main.py'
    )
    assert result.ok
    assert "2:     return 42" in result.output


def test_tree_lists_workspace_structure(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute("tree")
    assert result.ok
    assert "src/" in result.output
    assert "main.py" in result.output


@pytest.mark.parametrize("command", [
    "python -c 'print(1)'",
    "bash",
    "sh",
    "rm -rf .",
    "curl example.com",
    "git push",
])
def test_arbitrary_host_commands_are_not_available(terminal_workspace, command):
    result = ForgeVirtualTerminal(terminal_workspace).execute(command)
    assert not result.ok
    assert "not available" in result.output


@pytest.mark.parametrize("command", [
    "cat ../outside.txt",
    "ls ../../",
    "cd /etc",
])
def test_workspace_escape_is_blocked(terminal_workspace, command):
    result = ForgeVirtualTerminal(terminal_workspace).execute(command)
    assert not result.ok


@pytest.mark.parametrize("command", ["check", "build", "test"])
def test_development_execution_fails_closed(terminal_workspace, command):
    result = ForgeVirtualTerminal(terminal_workspace).execute(command)
    assert result.ok
    assert "BLOCKED" in result.output
    assert "No code was executed" in result.output


def test_toolchain_displays_registered_plan(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute("toolchain python")
    assert result.ok
    assert "python-isolated" in result.output
    assert "Execution enabled: False" in result.output


def test_missing_file_returns_error(terminal_workspace):
    result = ForgeVirtualTerminal(terminal_workspace).execute("cat missing.py")
    assert not result.ok


def test_invalid_workspace_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        ForgeVirtualTerminal(tmp_path / "missing")


def test_mkdir_creates_nested_workspace_directory(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("mkdir src/components")
    assert result.ok
    assert (terminal_workspace / "src" / "components").is_dir()


def test_touch_creates_workspace_file(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("touch src/new.py")
    assert result.ok
    assert (terminal_workspace / "src" / "new.py").read_text() == ""


def test_write_creates_and_replaces_file(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('write src/new.py "print(42)"')
    assert result.ok
    assert (terminal_workspace / "src" / "new.py").read_text() == "print(42)"
    terminal.execute('write src/new.py "print(99)"')
    assert (terminal_workspace / "src" / "new.py").read_text() == "print(99)"


def test_append_adds_to_existing_file(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('append README.md "Second line"')
    assert result.ok
    assert "Second line" in (terminal_workspace / "README.md").read_text()


def test_write_rejects_workspace_escape(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('write ../outside.txt "blocked"')
    assert not result.ok
    assert not (terminal_workspace.parent / "outside.txt").exists()


def test_write_rejects_missing_parent(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('write missing/file.py "blocked"')
    assert not result.ok


def test_touch_rejects_directory_target(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("touch src")
    assert not result.ok


def test_find_searches_workspace_recursively(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('find "return 42"')
    assert result.ok
    assert "src/main.py:2:" in result.output


def test_find_can_be_limited_to_directory(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute('find "return 42" src')
    assert result.ok
    assert "src/main.py" in result.output


def test_delete_removes_only_requested_file(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("delete README.md")
    assert result.ok
    assert not (terminal_workspace / "README.md").exists()


def test_delete_cannot_delete_directories(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("delete src")
    assert not result.ok
    assert (terminal_workspace / "src").is_dir()


def test_delete_cannot_escape_workspace(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    result = terminal.execute("delete ../outside.txt")
    assert not result.ok


def test_history_records_commands_without_recording_history_itself(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    terminal.execute("pwd")
    terminal.execute("ls")
    result = terminal.execute("history")
    assert result.ok
    assert "1: pwd" in result.output
    assert "2: ls" in result.output
    assert "history" not in result.output


def test_history_is_bounded(terminal_workspace):
    terminal = ForgeVirtualTerminal(terminal_workspace)
    for _ in range(210):
        terminal.execute("pwd")
    assert len(terminal._history) == 200
