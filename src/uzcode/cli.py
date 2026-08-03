"""CLI entry point for uzcode."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uzcode.data import Config, Request
from uzcode.engine import run as run_engine
from uzcode.extension import load_extensions


def _format_config(config: Config) -> str:
    lines = [
        f"work_dir: {config.work_dir}",
        "",
        "[llm]",
        f"  base_url:    {config.llm.base_url}",
        f"  api_key:     {config.llm.api_key}",
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

    if config.extension:
        lines.append("")
        lines.append("[extension]")
        for key, value in config.extension.items():
            if isinstance(value, list):
                lines.append(f"  {key}: {json.dumps(value)}")
            else:
                lines.append(f"  {key}: {value}")

    if config.exts:
        for name, opts in config.exts.items():
            lines.append("")
            lines.append(f"[exts.{name}]")
            if isinstance(opts, dict):
                for key, value in opts.items():
                    lines.append(f"  {key}: {value}")
            else:
                lines.append(f"  {opts}")

    return "\n".join(lines)


def _preview_content(content: str, limit: int = 200) -> str:
    preview = content.replace("\n", "\\n")
    if len(preview) > limit:
        return preview[: limit - 3] + "..."
    return preview


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
    parser.add_argument(
        "--out",
        default=None,
        help="Write result TOML to this path (default: overwrite --req)",
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

    try:
        registry = load_extensions(work_dir, config)
    except (FileNotFoundError, AttributeError, ImportError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        request = run_engine(config, request, out_path=args.out, registry=registry)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out).resolve() if args.out else request.path
    assistant = next(
        (m for m in reversed(request.messages) if m.role == "assistant"),
        None,
    )

    print("=== Result ===")
    print(f"wrote: {out}")
    print(f"messages: {len(request.messages)}")
    if assistant is not None:
        print(f"assistant: {_preview_content(assistant.content)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
