"""Extension: hook registry + loader."""

from uzcode.extension.base import HOOKS, HookRegistry
from uzcode.extension.loader import load_extensions

__all__ = ["HOOKS", "HookRegistry", "load_extensions"]
