"""Workspace file tools using descriptor-relative, no-symlink path traversal.

This narrows ordinary filesystem access; it is not a hostile-process sandbox.
"""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath

from pydantic import Field

from kairo_core.tools.registry import Schema, SideEffect, Tool, ToolContext, ToolError, ToolRegistry

MAX_BYTES = 1_048_576


class PathInput(Schema):
    path: str = Field(min_length=1, max_length=4096)


class WriteInput(PathInput):
    content: str = Field(max_length=MAX_BYTES)


class SearchInput(Schema):
    query: str = Field(min_length=1, max_length=1000)
    path: str = "."


class TextOutput(Schema):
    content: str


class WriteOutput(Schema):
    bytes_written: int


class EntriesOutput(Schema):
    entries: list[str]


def _parts(path: str) -> tuple[str, ...]:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "\x00" in path:
        raise ToolError("INVALID_PATH", "Expected a workspace-relative path without traversal")
    if any(part == ".git" or part == ".env" or part.startswith(".env.") for part in parsed.parts):
        raise ToolError("PROTECTED_PATH", "Metadata and environment files are protected")
    return parsed.parts


@contextmanager
def _parent(context: ToolContext, path: str) -> Iterator[tuple[int, str]]:
    parts = _parts(path)
    fd = os.open(context.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, parts[-1] if parts else "."
    finally:
        os.close(fd)


def _read(context: ToolContext, path: str) -> str:
    with _parent(context, path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_nlink != 1:
                raise ToolError("FILE_LIMIT", "Only bounded regular files can be read")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ToolError("FILE_LIMIT", "File exceeds read limit")
            return data.decode("utf-8")
        finally:
            os.close(fd)


async def read_file(value: PathInput, context: ToolContext) -> TextOutput:
    return TextOutput(content=_read(context, value.path))


async def write_file(value: WriteInput, context: ToolContext) -> WriteOutput:
    data = value.content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ToolError("FILE_LIMIT", "File exceeds write limit")
    with _parent(context, value.path) as (parent, name):
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ToolError(
                    "INVALID_FILE", "Only regular files without hard links can be written"
                )
            os.ftruncate(fd, 0)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                written = stream.write(data)
            return WriteOutput(bytes_written=written)
        finally:
            os.close(fd)


def _entries(context: ToolContext, path: str) -> list[str]:
    with _parent(context, path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            # scandir closes its iterator; cap work/output for consumer hardware.
            with os.scandir(fd) as items:
                names: list[str] = []
                for index, item in enumerate(items):
                    if index >= 1000:
                        raise ToolError("DIRECTORY_LIMIT", "Directory exceeds entry limit")
                    if item.name == ".git" or item.name.startswith(".env") or item.is_symlink():
                        continue
                    names.append(item.name)
                return sorted(names)
        finally:
            os.close(fd)


async def list_directory(value: PathInput, context: ToolContext) -> EntriesOutput:
    return EntriesOutput(entries=_entries(context, value.path))


async def search_files(value: SearchInput, context: ToolContext) -> EntriesOutput:
    # Deliberately a bounded, nonrecursive search in one directory. No regex engine.
    matches = []
    searched_bytes = 0
    for name in _entries(context, value.path):
        path = str(PurePosixPath(value.path) / name)
        try:
            content = _read(context, path)
            searched_bytes += len(content.encode("utf-8"))
            if searched_bytes > 4 * MAX_BYTES:
                raise ToolError("SEARCH_LIMIT", "Search exceeds 4 MiB budget")
            if value.query in content:
                matches.append(path)
        except ToolError as exc:
            if exc.code == "SEARCH_LIMIT":
                raise
            continue
        except (OSError, UnicodeError):
            continue  # Directories, binary or oversized files are not search candidates.
    return EntriesOutput(entries=matches)


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            "read_file",
            "Read a bounded UTF-8 workspace file",
            PathInput,
            TextOutput,
            read_file,
            "workspace.read",
        )
    )
    registry.register(
        Tool(
            "write_file",
            "Write a bounded UTF-8 workspace file; parent must exist",
            WriteInput,
            WriteOutput,
            write_file,
            "workspace.write",
            SideEffect.WORKSPACE_WRITE,
        )
    )
    registry.register(
        Tool(
            "list_directory",
            "List up to 1000 nonsymlink workspace entries",
            PathInput,
            EntriesOutput,
            list_directory,
            "workspace.read",
        )
    )
    registry.register(
        Tool(
            "search_files",
            "Literal text search in immediate directory files",
            SearchInput,
            EntriesOutput,
            search_files,
            "workspace.read",
        )
    )
