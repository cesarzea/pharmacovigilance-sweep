"""Download each pinned source file once into a local cache.

DuckDB's remote Parquet reader issues many range requests, which trips Hugging Face's per-IP rate
limit (HTTP 429). A plain download per file stays well under it. An optional HF_TOKEN raises the limit.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .sources import Source


def fetch(source: Source, path: str, cache_dir: Path) -> Path:
    target = cache_dir / source.key / source.revision / path
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = source.url(path)
    headers = {"User-Agent": "pvsweep-loader"}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    tmp = target.with_suffix(target.suffix + ".part")
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as rsp, tmp.open("wb") as out:  # noqa: S310
                while chunk := rsp.read(1 << 20):
                    out.write(chunk)
            tmp.replace(target)
            return target
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            wait = int(exc.headers.get("Retry-After", "60")) + 5
            print(f"  rate limited by huggingface.co, waiting {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"could not download {url}")
