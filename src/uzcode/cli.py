"""CLI entry point for uzcode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uzcode.data import Config, Request


def _format_config(config: Config) -> str:
    lines = [
        f"work_dir: {config.work_dir}",
        "",
        "[llm]",
        f"  base_url:    {config.llm.base_url}",
        f"  api_key_env: {config.llm.api_key_env}",
        f"  model:       {config.llm.model}",
        "",
        "[loop]",
        f"  auto_loop:       {config.loop.auto_loop}",
        f"  max_iterations:  {config.loop.max_iterations}",
    ]

    if config.tools:
        lines.append("")
        for name, opts in config.tools.items():
            lines.append(f"[tools.{name}]")
            for key, value in opts.items():
                lines.append(f"  {key}: {value}")

    if config.middleware:
        lines.append("")
        lines.append("[middleware]")
        for key, value in config.middleware.items():
            if isinstance(value, list):
                lines.append(f"  {key}: {json.dumps(value)}")
            else:
                lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def _format_messages(request: Request) -> str:
    lines = [f"req: {request.path}", f"messages: {len(request.messages)}", ""]
    for i, msg in enumerate(request.messages):
        lines.append(f"[{i}] role={msg.role}")
        preview = msg.content.replace("\n", "\\n")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        lines.append(f"    content: {preview!r}")
        if msg.extra:
            lines.append(f"    extra: {json.dumps(msg.extra, ensure_ascii=False)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uzcode",
        description="Minimal, stateless AI coding agent",
    )
    parser.add_argument(
        "--workdir",
        default=".",
        help="Working directory containing .uzcode/cfg.toml (default: .)",
    )
    parser.add_argument(
        "--req",
        default="req.toml",
        help="Path to request TOML file (default: req.toml)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.workdir).resolve()

    try:
        config = Config.load(work_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        request = Request.load(args.req, work_dir=work_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("=== Config ===")
    print(_format_config(config))
    print()
    print("=== Request ===")
    print(_format_messages(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
