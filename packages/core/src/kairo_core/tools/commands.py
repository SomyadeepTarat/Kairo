"""Command tools require an explicit executor; no implicit host shell fallback."""

from pydantic import Field

from kairo_core.tools.registry import (
    CommandResult,
    Schema,
    SideEffect,
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
)


class CommandInput(Schema):
    argv: list[str] = Field(min_length=1, max_length=64)


class EmptyInput(Schema):
    pass


async def execute_command(value: CommandInput, context: ToolContext) -> CommandResult:
    if any(not argument or "\x00" in argument or len(argument) > 4096 for argument in value.argv):
        raise ToolError("INVALID_INPUT", "Invalid command argument")
    if context.command_executor is None:
        raise ToolError("EXECUTOR_UNAVAILABLE", "An isolated executor is required")
    return await context.command_executor.execute(tuple(value.argv), context.workspace)


async def git_status(value: EmptyInput, context: ToolContext) -> CommandResult:
    return await execute_command(
        CommandInput(argv=["git", "--no-optional-locks", "status", "--porcelain=v1"]), context
    )


async def git_diff(value: EmptyInput, context: ToolContext) -> CommandResult:
    return await execute_command(
        CommandInput(argv=["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv"]), context
    )


def register_command_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            "execute_command",
            "Execute explicit argv using a supplied isolated executor",
            CommandInput,
            CommandResult,
            execute_command,
            "command.execute",
            SideEffect.EXTERNAL,
        )
    )
    registry.register(
        Tool(
            "git_status",
            "Inspect Git status through the command executor",
            EmptyInput,
            CommandResult,
            git_status,
            "command.execute",
        )
    )
    registry.register(
        Tool(
            "git_diff",
            "Inspect Git diff through the command executor",
            EmptyInput,
            CommandResult,
            git_diff,
            "command.execute",
        )
    )
