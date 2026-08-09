"""Extension: hook registry + loader."""

from uzcode.extension.base import HOOKS, ActionFn, HookFn, HookRegistry
from uzcode.extension.loader import load_extensions

__all__ = ["HOOKS", "ActionFn", "HookFn", "HookRegistry", "load_extensions"]
