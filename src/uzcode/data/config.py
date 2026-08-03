"""Load and parse .uzcode/cfg.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o"


@dataclass
class LoopConfig:
    auto_loop: bool = True
    max_iterations: int = 20


@dataclass
class Config:
    """Global settings loaded from {work_dir}/.uzcode/cfg.toml."""

    work_dir: Path
    llm: LLMConfig = field(default_factory=LLMConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    extension: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, work_dir: str | Path) -> Config:
        work_dir = Path(work_dir).resolve()
        cfg_path = work_dir / ".uzcode" / "cfg.toml"

        if not cfg_path.is_file():
            raise FileNotFoundError(
                f"Config not found: {cfg_path}\n"
                f"Create .uzcode/cfg.toml in your work directory."
            )

        with cfg_path.open("rb") as f:
            raw = tomllib.load(f)

        llm_raw = raw.get("llm", {})
        loop_raw = raw.get("loop", {})

        return cls(
            work_dir=work_dir,
            llm=LLMConfig(
                base_url=llm_raw.get("base_url", LLMConfig.base_url),
                api_key=llm_raw.get("api_key"),
                api_key_env=llm_raw.get("api_key_env", LLMConfig.api_key_env),
                model=llm_raw.get("model", LLMConfig.model),
            ),
            loop=LoopConfig(
                auto_loop=loop_raw.get("auto_loop", LoopConfig.auto_loop),
                max_iterations=loop_raw.get("max_iterations", LoopConfig.max_iterations),
            ),
            tools=raw.get("tools", {}),
            extension=raw.get("extension", {}),
            raw=raw,
        )
