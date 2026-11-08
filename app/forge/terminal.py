"""Safe virtual terminal for isolated Amination Forge workspaces.

This module deliberately does not invoke a host shell or execute generated code.
It exposes a small, auditable command language over a supplied workspace root.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.forge.toolchains import build_toolchain_plan


MAX_READ_BYTES = 256 * 1024
MAX_WRITE_BYTES = 256 * 1024
MAX_TREE_ENTRIES = 200
MAX_TREE_DEPTH = 4
MAX_SEARCH_FILES = 500
MAX_HISTORY = 200


@dataclass(frozen=True)
class TerminalResult:
    command: str
    output: str
    exit_code: int = 0
    cwd: str = "."

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "output": self.output,
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "ok": self.ok,
        }


class ForgeTerminalError(ValueError):
    """Raised when a terminal workspace or command is invalid."""


class ForgeVirtualTerminal:
    """A non-shell terminal scoped to one Forge workspace."""

    COMMANDS = (
        "help", "pwd", "cd", "ls", "tree", "cat", "grep",
        "mkdir", "touch", "write", "append", "find", "delete", "history", "toolchain", "check", "build", "test", "run",
    )

    HELP = """Amination Forge virtual terminal

Workspace commands:
  help                       Show this help
  pwd                        Show the current workspace directory
  cd <directory>             Change virtual working directory
  ls [directory]             List files and directories
  tree [directory]           Show a bounded directory tree
  cat <file>                 Read a UTF-8 text file
  grep <text> <file>         Search for literal text in a file
  mkdir <directory>         Create a workspace directory
  touch <file>              Create an empty file
  write <file> <text>       Replace a UTF-8 text file\n  append <file> <text>      Append UTF-8 text to a file\n  find <text> [directory]  Search workspace file contents\n  delete <file>            Delete one workspace file\n  history                  Show recent terminal commands\n  toolchain <language>       Show the registered toolchain plan

Development commands:
  check                      Request static validation
  build                      Request an isolated build
  test                       Request isolated tests

Execution is disabled until a trusted isolated runner is connected.
No host shell, arbitrary command, or generated-code execution is available.
"""

    def __init__(self, workspace_root: str | Path):
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ForgeTerminalError("Workspace root must be an existing directory.")
        self._root = root
        self._cwd = root
        self._history: list[str] = []

    @property
    def cwd(self) -> str:
        relative = self._cwd.relative_to(self._root)
        return "." if str(relative) == "." else relative.as_posix()

    def _resolve(self, raw: str = ".") -> Path:
        if not raw or "\x00" in raw:
            raise ForgeTerminalError("A valid workspace path is required.")

        candidate = Path(raw)
        if candidate.is_absolute():
            raise ForgeTerminalError("Absolute paths are not allowed.")

        resolved = (self._cwd / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ForgeTerminalError("Path escapes the Forge workspace.") from exc

        return resolved

    @staticmethod
    def _text_file(path: Path) -> str:
        if not path.is_file():
            raise ForgeTerminalError("The requested path is not a file.")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ForgeTerminalError(
                f"File exceeds the {MAX_READ_BYTES}-byte terminal read limit."
            )
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ForgeTerminalError("Only UTF-8 text files can be displayed.") from exc

    def _list(self, path: Path) -> str:
        if not path.is_dir():
            raise ForgeTerminalError("The requested path is not a directory.")
        entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        if not entries:
            return "(empty directory)"
        return "\n".join(
            f"{item.name}/" if item.is_dir() else item.name
            for item in entries[:MAX_TREE_ENTRIES]
        )

    def _tree(self, path: Path) -> str:
        if not path.is_dir():
            raise ForgeTerminalError("The requested path is not a directory.")

        lines = [path.name or "."]
        count = 0

        def walk(directory: Path, prefix: str, depth: int) -> None:
            nonlocal count
            if depth >= MAX_TREE_DEPTH or count >= MAX_TREE_ENTRIES:
                return

            entries = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
            for index, item in enumerate(entries):
                if count >= MAX_TREE_ENTRIES:
                    lines.append(prefix + "... entry limit reached")
                    return
                count += 1
                last = index == len(entries) - 1
                branch = "`-- " if last else "|-- "
                suffix = "/" if item.is_dir() else ""
                lines.append(prefix + branch + item.name + suffix)
                if item.is_dir():
                    walk(item, prefix + ("    " if last else "|   "), depth + 1)

        walk(path, "", 0)
        return "\n".join(lines)

    def execute(self, command: str) -> TerminalResult:
        raw = command.strip()
        if not raw:
            return TerminalResult(command, "", 0, self.cwd)

        if raw != "history":
            self._history.append(raw)
            self._history = self._history[-MAX_HISTORY:]

        try:
            tokens = shlex.split(raw, posix=True)
            if not tokens:
                return TerminalResult(command, "", 0, self.cwd)

            name, *args = tokens
            if name not in self.COMMANDS:
                raise ForgeTerminalError(
                    f"Command not available: {name!r}. Use 'help' for supported commands."
                )

            output = self._dispatch(name, args)
            return TerminalResult(command, output, 0, self.cwd)

        except (ForgeTerminalError, ValueError) as exc:
            return TerminalResult(command, str(exc), 2, self.cwd)

    def _dispatch(self, name: str, args: list[str]) -> str:
        if name == "help":
            if args:
                raise ForgeTerminalError("'help' takes no arguments.")
            return self.HELP

        if name == "pwd":
            if args:
                raise ForgeTerminalError("'pwd' takes no arguments.")
            return self.cwd

        if name == "cd":
            if len(args) > 1:
                raise ForgeTerminalError("Usage: cd <directory>")
            destination = self._resolve(args[0] if args else ".")
            if not destination.is_dir():
                raise ForgeTerminalError("The requested directory does not exist.")
            self._cwd = destination
            return self.cwd

        if name == "ls":
            if len(args) > 1:
                raise ForgeTerminalError("Usage: ls [directory]")
            return self._list(self._resolve(args[0] if args else "."))

        if name == "tree":
            if len(args) > 1:
                raise ForgeTerminalError("Usage: tree [directory]")
            return self._tree(self._resolve(args[0] if args else "."))

        if name == "cat":
            if len(args) != 1:
                raise ForgeTerminalError("Usage: cat <file>")
            return self._text_file(self._resolve(args[0]))

        if name == "grep":
            if len(args) != 2:
                raise ForgeTerminalError("Usage: grep <text> <file>")
            needle, path = args
            content = self._text_file(self._resolve(path))
            matches = [
                f"{number}: {line}"
                for number, line in enumerate(content.splitlines(), 1)
                if needle in line
            ]
            return "\n".join(matches) if matches else "(no matches)"

        if name == "mkdir":
            if len(args) != 1:
                raise ForgeTerminalError("Usage: mkdir <directory>")
            destination = self._resolve(args[0])
            destination.mkdir(parents=True, exist_ok=True)
            if not destination.is_dir():
                raise ForgeTerminalError("Could not create the requested directory.")
            return f"Directory ready: {destination.relative_to(self._root).as_posix()}"

        if name == "touch":
            if len(args) != 1:
                raise ForgeTerminalError("Usage: touch <file>")
            destination = self._resolve(args[0])
            if destination.exists() and not destination.is_file():
                raise ForgeTerminalError("The requested path is not a file.")
            if not destination.parent.is_dir():
                raise ForgeTerminalError("Parent directory does not exist.")
            if not destination.exists():
                destination.write_text("", encoding="utf-8")
            return f"File ready: {destination.relative_to(self._root).as_posix()}"

        if name in {"write", "append"}:
            if len(args) < 2:
                raise ForgeTerminalError(f"Usage: {name} <file> <text>")
            destination = self._resolve(args[0])
            content = " ".join(args[1:])
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_WRITE_BYTES:
                raise ForgeTerminalError(
                    f"Text exceeds the {MAX_WRITE_BYTES}-byte write limit."
                )
            if not destination.parent.is_dir():
                raise ForgeTerminalError("Parent directory does not exist.")
            if destination.exists() and not destination.is_file():
                raise ForgeTerminalError("The requested path is not a file.")
            if name == "append" and destination.exists():
                if destination.stat().st_size + len(encoded) > MAX_WRITE_BYTES:
                    raise ForgeTerminalError("Resulting file exceeds the write limit.")
                with destination.open("a", encoding="utf-8") as handle:
                    handle.write(content)
            else:
                destination.write_text(content, encoding="utf-8")
            return f"File {'updated' if name == 'write' else 'appended'}: {destination.relative_to(self._root).as_posix()}"

        if name == "history":
            if args:
                raise ForgeTerminalError("'history' takes no arguments.")
            if not self._history:
                return "(no command history)"
            start = max(1, len(self._history) - MAX_HISTORY + 1)
            return "\\n".join(
                f"{index}: {item}"
                for index, item in enumerate(self._history, start)
            )

        if name == "delete":
            if len(args) != 1:
                raise ForgeTerminalError("Usage: delete <file>")
            destination = self._resolve(args[0])
            if not destination.exists() or not destination.is_file():
                raise ForgeTerminalError("Only an existing file can be deleted.")
            destination.unlink()
            return f"Deleted file: {destination.relative_to(self._root).as_posix()}"

        if name == "find":
            if len(args) not in {1, 2}:
                raise ForgeTerminalError("Usage: find <text> [directory]")
            needle = args[0]
            base = self._resolve(args[1] if len(args) == 2 else ".")
            if not base.is_dir():
                raise ForgeTerminalError("Search location must be a directory.")

            matches: list[str] = []
            scanned = 0
            for candidate in base.rglob("*"):
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                scanned += 1
                if scanned > MAX_SEARCH_FILES:
                    matches.append("Search stopped: file limit reached.")
                    break
                try:
                    if candidate.stat().st_size > MAX_READ_BYTES:
                        continue
                    content = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                relative = candidate.relative_to(self._root).as_posix()
                for line_number, line in enumerate(content.splitlines(), 1):
                    if needle in line:
                        matches.append(f"{relative}:{line_number}: {line}")
                        if len(matches) >= MAX_TREE_ENTRIES:
                            matches.append("Search result limit reached.")
                            return "\\n".join(matches)
            return "\\n".join(matches) if matches else "(no matches)"

        if name == "toolchain":
            if len(args) != 1:
                raise ForgeTerminalError("Usage: toolchain <language>")
            plan = build_toolchain_plan(args[0])
            if not isinstance(plan, dict):
                raise ForgeTerminalError("Toolchain returned an invalid plan.")

            lines = [
                f"{key.replace('_', ' ').title()}: {value}"
                for key, value in sorted(plan.items())
            ]
            enabled = plan.get("execution_enabled", False)
            lines.append(f"Execution enabled: {enabled}")
            return "\\n".join(lines)

        if name == "run":
            raise ForgeTerminalError(
                "RUN BLOCKED: connect the trusted independent Linux runner through "
                "ForgeTerminalService. No code was executed locally."
            )

        if name in {"check", "build", "test"}:
            if args:
                raise ForgeTerminalError(f"'{name}' takes no arguments.")
            return (
                f"{name.upper()} BLOCKED: trusted isolated runner is not connected. "
                "No code was executed."
            )

        raise ForgeTerminalError("Unsupported terminal operation.")
