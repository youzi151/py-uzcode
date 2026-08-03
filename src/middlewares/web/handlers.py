"""web_search / web_fetch tool handlers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
import trafilatura
from ddgs import DDGS

_DEFAULT_MAX_RESULTS = 5
_DEFAULT_BACKEND = "auto"
_DEFAULT_MAX_CHARS = 32 * 1024
_DEFAULT_TIMEOUT_SEC = 30.0
_MAX_RESULTS_CAP = 20
_MAX_CHARS_CAP = 200_000
_MAX_TIMEOUT_SEC = 120.0
_USER_AGENT = "uzcode-web"


def _clamp_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clamp_float(value: Any, default: float, *, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _http_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return raw


def search_results(
    query: str,
    *,
    max_results: int = _DEFAULT_MAX_RESULTS,
    backend: str = _DEFAULT_BACKEND,
) -> list[dict[str, str]]:
    """Return normalized search hits: title, url, snippet."""
    q = (query or "").strip()
    if not q:
        return []
    max_results = _clamp_int(
        max_results, _DEFAULT_MAX_RESULTS, lo=1, hi=_MAX_RESULTS_CAP
    )
    backend = (backend or _DEFAULT_BACKEND).strip() or _DEFAULT_BACKEND
    kwargs: dict[str, Any] = {"max_results": max_results}
    if backend and backend != "auto":
        kwargs["backend"] = backend
    else:
        kwargs["backend"] = "auto"
    raw = DDGS().text(q, **kwargs)
    out: list[dict[str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("href") or item.get("url") or "").strip()
        snippet = str(item.get("body") or item.get("snippet") or "").strip()
        if not title and not url:
            continue
        out.append({"title": title or "(no title)", "url": url, "snippet": snippet})
    return out


def format_search_index(query: str, results: list[dict[str, str]]) -> str:
    """Title + link index for mention expand (no snippets)."""
    q = (query or "").strip() or "(empty)"
    if not results:
        return f"[search: {q} | (no results)]"
    lines = [f"[search: {q}]"]
    for i, hit in enumerate(results, start=1):
        title = hit.get("title") or "(no title)"
        url = hit.get("url") or ""
        if url:
            lines.append(f"{i}. {title} | {url}")
        else:
            lines.append(f"{i}. {title}")
    return "\n".join(lines)


def format_search_full(query: str, results: list[dict[str, str]]) -> str:
    """Full tool result: title / url / snippet."""
    q = (query or "").strip() or "(empty)"
    if not results:
        return f"query: {q}\n(no results)"
    lines = [f"query: {q}", f"results: {len(results)}", ""]
    for i, hit in enumerate(results, start=1):
        title = hit.get("title") or "(no title)"
        url = hit.get("url") or ""
        snippet = hit.get("snippet") or ""
        lines.append(f"{i}. {title}")
        if url:
            lines.append(f"   url: {url}")
        if snippet:
            lines.append(f"   snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _extract_title(html: str, url: str) -> str:
    meta = trafilatura.extract_metadata(html, default_url=url)
    if meta is not None:
        title = getattr(meta, "title", None)
        if title and str(title).strip():
            return str(title).strip()
    m = re.search(
        r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL
    )
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        if title:
            return title
    return ""


def fetch_page(
    url: str,
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, str]:
    """Fetch URL; return dict with keys url, title, text — or error."""
    checked = _http_url(url)
    if checked is None:
        return {"error": "url must be an http(s) URL"}

    timeout = _clamp_float(
        timeout_sec, _DEFAULT_TIMEOUT_SEC, lo=1.0, hi=_MAX_TIMEOUT_SEC
    )
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = client.get(checked)
    except httpx.TimeoutException:
        return {"error": f"request timed out after {timeout:g}s"}
    except httpx.HTTPError as exc:
        return {"error": f"request failed: {exc}"}

    final_url = str(resp.url)
    content_type = (resp.headers.get("content-type") or "").lower()
    if content_type and not any(
        t in content_type
        for t in ("text/", "json", "xml", "html", "xhtml", "javascript")
    ):
        if "octet-stream" in content_type or "image/" in content_type:
            return {
                "error": f"unsupported content-type: {content_type}",
                "url": final_url,
            }

    try:
        html = resp.text
    except Exception as exc:  # noqa: BLE001
        return {"error": f"failed to decode response body: {exc}", "url": final_url}

    if resp.status_code >= 400:
        return {
            "error": f"HTTP {resp.status_code}",
            "url": final_url,
            "title": _extract_title(html, final_url),
        }

    title = _extract_title(html, final_url)
    text = trafilatura.extract(
        html,
        url=final_url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
    )
    if not text or not str(text).strip():
        # Fallback: plain text extraction
        text = trafilatura.extract(
            html,
            url=final_url,
            output_format="txt",
            include_comments=False,
        )
    body = (text or "").strip()
    if not body:
        return {
            "error": "no readable text extracted",
            "url": final_url,
            "title": title,
        }
    return {"url": final_url, "title": title, "text": body}


def format_fetch_index(url: str, title: str = "") -> str:
    """Short index for mention expand (no body)."""
    u = (url or "").strip() or "(empty)"
    t = (title or "").strip()
    if t:
        return f"[fetch: {u} | title: {t}]"
    return f"[fetch: {u}]"


def format_fetch_full(
    url: str,
    title: str,
    text: str,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    max_chars = _clamp_int(max_chars, _DEFAULT_MAX_CHARS, lo=256, hi=_MAX_CHARS_CAP)
    body = text or ""
    omitted = 0
    if len(body) > max_chars:
        omitted = len(body) - max_chars
        body = body[:max_chars]
    lines = [f"url: {url}"]
    if title:
        lines.append(f"title: {title}")
    lines.append("")
    lines.append(body)
    if omitted:
        lines.append("")
        lines.append(f"...[truncated {omitted} chars]")
    return "\n".join(lines)


def search_defaults(cfg: dict[str, Any] | None) -> tuple[int, str]:
    cfg = cfg or {}
    max_results = _clamp_int(
        cfg.get("max_results", _DEFAULT_MAX_RESULTS),
        _DEFAULT_MAX_RESULTS,
        lo=1,
        hi=_MAX_RESULTS_CAP,
    )
    backend = str(cfg.get("backend", _DEFAULT_BACKEND) or "").strip() or _DEFAULT_BACKEND
    return max_results, backend


def fetch_defaults(cfg: dict[str, Any] | None) -> tuple[int, float]:
    cfg = cfg or {}
    max_chars = _clamp_int(
        cfg.get("max_chars", _DEFAULT_MAX_CHARS),
        _DEFAULT_MAX_CHARS,
        lo=256,
        hi=_MAX_CHARS_CAP,
    )
    timeout_sec = _clamp_float(
        cfg.get("timeout_sec", _DEFAULT_TIMEOUT_SEC),
        _DEFAULT_TIMEOUT_SEC,
        lo=1.0,
        hi=_MAX_TIMEOUT_SEC,
    )
    return max_chars, timeout_sec


def make_web_search(*, default_max_results: int, default_backend: str):
    def web_search(args: dict[str, Any], ctx: dict[str, Any]) -> str:  # noqa: ARG001
        query = str(args.get("query", "") or "")
        if not query.strip():
            return "Error: query is required"
        max_results = args.get("max_results", default_max_results)
        max_results = _clamp_int(
            max_results, default_max_results, lo=1, hi=_MAX_RESULTS_CAP
        )
        try:
            results = search_results(
                query, max_results=max_results, backend=default_backend
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error: web_search failed: {exc}"
        return format_search_full(query, results)

    return web_search


def make_web_fetch(*, default_max_chars: int, default_timeout_sec: float):
    def web_fetch(args: dict[str, Any], ctx: dict[str, Any]) -> str:  # noqa: ARG001
        url = str(args.get("url", "") or "")
        if not url.strip():
            return "Error: url is required"
        timeout = args.get("timeout_sec", default_timeout_sec)
        timeout_f = _clamp_float(
            timeout, default_timeout_sec, lo=1.0, hi=_MAX_TIMEOUT_SEC
        )
        page = fetch_page(url, timeout_sec=timeout_f)
        if "error" in page and "text" not in page:
            err = page["error"]
            final = page.get("url") or url
            title = page.get("title") or ""
            parts = [f"Error: {err}", f"url: {final}"]
            if title:
                parts.append(f"title: {title}")
            return "\n".join(parts)
        return format_fetch_full(
            page.get("url") or url,
            page.get("title") or "",
            page.get("text") or "",
            max_chars=default_max_chars,
        )

    return web_fetch
