"""CLI entry point for uzcode."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from overdict import merge

import uzcode
from uzcode import CodingAgent
from uzcode.data import Config, Request


def resolve_cfg_path(token: str, work_dir: str | Path) -> Path:
    """Resolve a --cfg token to a TOML file path.

    Order: existing user path → ``{work_dir}/.uzcode/cfgs/{name}.toml`` →
    built-in ``uzcode/cfgs/{name}.toml``. Extension ``.toml`` is optional.
    """
    work_dir = Path(work_dir).resolve()
    raw = token.strip()
    name = raw[:-5] if raw.lower().endswith(".toml") else raw

    candidates: list[Path] = []
    as_path = Path(raw)
    if as_path.is_absolute():
        candidates.append(as_path)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(work_dir / raw)
        if raw != name:
            candidates.append(Path.cwd() / name)
            candidates.append(work_dir / name)
        else:
            candidates.append(Path.cwd() / f"{name}.toml")
            candidates.append(work_dir / f"{name}.toml")

    for path in candidates:
        if path.is_file():
            return path.resolve()

    project = work_dir / ".uzcode" / "cfgs" / f"{name}.toml"
    if project.is_file():
        return project.resolve()

    builtin = Path(uzcode.__file__).resolve().parent / "cfgs" / f"{name}.toml"
    if builtin.is_file():
        return builtin.resolve()

    raise FileNotFoundError(
        f"Config not found for {token!r}. Tried user path, "
        f"{project}, and built-in {builtin}."
    )


def load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"TOML root must be a table: {path}")
    return data


def _normalize_redirect(value: Any, path: Path) -> list[str]:
    if isinstance(value, str):
        tokens = [value]
    elif isinstance(value, list):
        tokens = value
    else:
        raise ValueError(
            f"redirect in {path} must be a string or list of strings"
        )
    if not tokens:
        raise ValueError(f"redirect in {path} must not be empty")
    out: list[str] = []
    for item in tokens:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"redirect in {path} must contain only non-empty strings"
            )
        out.append(item.strip())
    return out


def _expand_under_redirect(
    token: str,
    work_dir: Path,
    redirected: list[Path],
    paths: list[Path],
    cfg_dicts: list[dict[str, Any]],
) -> None:
    """Expand one token under a root redirect's redirected list."""
    path = resolve_cfg_path(token, work_dir)
    if path in redirected:
        return
    redirected.append(path)
    data = load_toml(path)
    if "redirect" in data:
        if len(data) > 1:
            print(
                f"Warning: {path} has redirect; other keys are ignored",
                file=sys.stderr,
            )
        for sub in _normalize_redirect(data["redirect"], path):
            _expand_under_redirect(sub, work_dir, redirected, paths, cfg_dicts)
        return
    paths.append(path)
    cfg_dicts.append(data)


def expand_cfg_layers(
    tokens: list[str],
    work_dir: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Resolve --cfg tokens, expand redirect files, return leaf layers.

    Each top-level redirect owns a temporary redirected list. Nested redirects
    share that list; targets already listed are skipped.
    """
    work_dir = Path(work_dir).resolve()
    paths: list[Path] = []
    cfg_dicts: list[dict[str, Any]] = []

    for token in tokens:
        path = resolve_cfg_path(token, work_dir)
        data = load_toml(path)
        if "redirect" not in data:
            paths.append(path)
            cfg_dicts.append(data)
            continue

        if len(data) > 1:
            print(
                f"Warning: {path} has redirect; other keys are ignored",
                file=sys.stderr,
            )
        redirected: list[Path] = [path]
        for sub in _normalize_redirect(data["redirect"], path):
            _expand_under_redirect(sub, work_dir, redirected, paths, cfg_dicts)

    return paths, cfg_dicts


def prepare_config_request(
    work_dir: Path,
    cfg_dicts: list[dict[str, Any]],
    *,
    out_path: Path,
) -> tuple[Config, Request]:
    """Merge cfg layers with overdict and split into Config + Request."""
    if not cfg_dicts:
        raise ValueError("cfg_dicts must not be empty")
    merged = dict(merge(*cfg_dicts))
    req_raw = merged.pop("request", None)
    if not isinstance(req_raw, dict):
        req_raw = {}
    config = Config.from_dict(work_dir, merged)
    request = Request.from_dict(out_path, work_dir, req_raw)
    return config, request


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
            "Config/request TOML layers in merge order. "
            "Built-in name, .uzcode/cfgs/ name, or file path; .toml optional."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write request result TOML (default: {workdir}/output_<timestamp>.toml)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.workdir).resolve()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else Path(f"output_{stamp}.toml")
    if not out_path.is_absolute():
        out_path = (work_dir / out_path).resolve()

    try:
        paths, cfg_dicts = expand_cfg_layers(args.cfg, work_dir)
        config, request = prepare_config_request(
            work_dir, cfg_dicts, out_path=out_path
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("=== Config ===")
    print(_format_config(config))
    print()
    print(f"cfg layers: {', '.join(str(p) for p in paths)}")
    print(f"request messages: {len(request.messages)}")
    print(f"out: {out_path}")
    print()

    try:
        request = CodingAgent(work_dir).run(config, request, out_path=out_path)
    except (FileNotFoundError, AttributeError, ImportError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    assistant = next(
        (m for m in reversed(request.messages) if m.role == "assistant"),
        None,
    )

    print("=== Result ===")
    print(f"wrote: {request.path}")
    print(f"messages: {len(request.messages)}")
    if assistant is not None:
        print(f"assistant: {_preview_content(assistant.content)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
