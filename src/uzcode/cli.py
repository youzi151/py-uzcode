"""CLI entry point for uzcode."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from uzcode import CodingAgent
from uzcode.data import Config
from uzcode.data.request import copy_request_to_reqbak, persist_session


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
        help="Project working directory (default: .)",
    )
    parser.add_argument(
        "--cfg",
        nargs="+",
        required=True,
        metavar="NAME_OR_PATH",
        help=(
            "Config TOML layers in merge order (may include [request]). "
            "Session request.toml is appended as the last layer. "
            "Built-in name, .uzcode/cfgs/ name, or file path; .toml optional."
        ),
    )
    parser.add_argument(
        "--session",
        required=True,
        metavar="NAME",
        help=(
            "Session name under {workdir}/.uzcode/sessions/<NAME>/ "
            "(request.toml is a normal last cfg layer; updated after run)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.workdir).resolve()
    agent = CodingAgent(work_dir)

    try:
        config, request, meta = agent.prepare(args.cfg, args.session)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("=== Config ===")
    print(_format_config(config))
    print()
    print(f"cfg layers: {', '.join(str(p) for p in meta.cfg_paths)}")
    print(f"session: {meta.session_dir}")
    print(f"request: {meta.request_path}")
    print(f"request messages: {len(request.messages)}")
    print()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    copy_request_to_reqbak(meta.session_dir, stamp)

    try:
        request, appended = agent.run(config, request)
    except (FileNotFoundError, AttributeError, ImportError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    persist_session(meta.session_dir, request, appended, stamp=stamp)

    assistant = next(
        (m for m in reversed(request.messages) if m.role == "assistant"),
        None,
    )

    print("=== Result ===")
    print(f"session: {meta.session_dir}")
    print(f"wrote: {request.path}")
    print(f"messages: {len(request.messages)}")
    if assistant is not None:
        print(f"assistant: {_preview_content(assistant.content)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
