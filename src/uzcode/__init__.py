"""uzcode — a minimal, stateless AI coding agent."""

from uzcode.data import Config, Request

__all__ = ["CodingAgent", "Config", "Request"]


class CodingAgent:
    """Public API entry point (Phase 5 will flesh out run())."""

    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir

    def run(self, request_path: str = "req.toml") -> Request:
        """Load config and request; full engine loop comes in later phases."""
        config = Config.load(self.work_dir)
        request = Request.load(request_path, work_dir=self.work_dir)
        return request
