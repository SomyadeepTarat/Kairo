"""Built-in tools; constructing a registry never executes anything."""

from kairo_core.tools.commands import register_command_tools
from kairo_core.tools.files import register_file_tools
from kairo_core.tools.registry import ToolRegistry


def builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_file_tools(registry)
    register_command_tools(registry)
    return registry
