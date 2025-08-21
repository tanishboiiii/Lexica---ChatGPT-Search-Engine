from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime

from .index_bm25 import bm25_search

def _within(ts: str, after_iso: str | None, before_iso: str | None) -> bool:
    if not ts: return True
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return True
    if after_iso:
        try:
            a = datetime.fromisoformat(after_iso)
            if t < a: return False
        except Exception:
            pass
    if before_iso:
        try:
            b = datetime.fromisoformat(before_iso)
            if t > b: return False
        except Exception:
            pass
    return True

def _load_rows(ddir: Path):
    rows = []
    with (ddir / "rows.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows

def search_bm25_with_snippets(
    ddir: Path, q: str, k: int = 10,
    role: str | None = None,
    has_code: bool | None = None,
    after_iso: str | None = None,
    before_iso: str | None = None,
    conv_id: str | None = None
):
    meta = json.loads((ddir / "meta.json").read_text(encoding="utf-8"))
    rows = _load_rows(ddir)
    text_by_id = {int(r["msg"]): r.get("text") for r in rows}

    base = bm25_search(ddir, q, topk=200)
    out = []
    for r in base:
        m = int(r["msg"])
        mm = meta.get(str(m), {})
        if conv_id and mm.get("conv_id") != conv_id:
            continue
        if role and (mm.get("role") or "").lower() != role.lower():
            continue
        if has_code is not None and bool(mm.get("has_code", False)) != has_code:
            continue
        if not _within(mm.get("ts") or "", after_iso, before_iso):
            continue
        r["snippet"] = text_by_id.get(m) or mm.get("snippet") or ""
        out.append(r)
        if len(out) >= k:
            break
    return out

def get_conversation(ddir: Path, conv_id: str, center_msg: int | None = None, window: int = 15):
    # Try threads.json (if your parser writes it); else scan rows.jsonl
    tpath = ddir / "threads.json"
    if tpath.exists():
        threads = json.loads(tpath.read_text(encoding="utf-8"))
        conv = threads.get(conv_id)
        if conv:
            msgs = conv["messages"]
            if center_msg is None:
                return {"conv_id": conv_id, "messages": msgs}
            idx = next((i for i, m in enumerate(msgs) if int(m["msg"]) == int(center_msg)), None)
            if idx is None:
                return {"conv_id": conv_id, "messages": msgs[:window*2+1]}
            lo = max(0, idx - window)
            hi = min(len(msgs), idx + window + 1)
            return {"conv_id": conv_id, "messages": msgs[lo:hi]}

    # Fallback: filter rows.jsonl by conv_id
    rows = []
    with (ddir / "rows.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("conv_id") == conv_id:
                rows.append(r)
    rows.sort(key=lambda x: x.get("msg"))
    if center_msg is None:
        return {"conv_id": conv_id, "messages": rows}
    idx = next((i for i, m in enumerate(rows) if int(m["msg"]) == int(center_msg)), None)
    if idx is None:
        return {"conv_id": conv_id, "messages": rows[:window*2+1]}
    lo = max(0, idx - window)
    hi = min(len(rows), idx + window + 1)
    return {"conv_id": conv_id, "messages": rows[lo:hi]}
