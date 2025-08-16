# backend/app/parse.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
import json
import re
import time
import zipfile

SYSTEM_ROLES = {"system"}  # filter these out
CODE_FENCE_RE = re.compile(r"```")
INLINE_CODE_RE = re.compile(r"`[^`]+`")
WORD_RE = re.compile(r"[a-z0-9]+")


def _has_code(text: str) -> bool:
    return bool(CODE_FENCE_RE.search(text) or INLINE_CODE_RE.search(text))


def _message_text(msg_obj: Dict[str, Any]) -> str:
    """
    Your sample uses:
      message: {
        content: { content_type: "text", parts: ["..."] }
      }
    We join non-empty string parts with newlines and ignore empty strings.
    """
    if not msg_obj:
        return ""
    content = (msg_obj or {}).get("content") or {}
    parts = content.get("parts")
    if isinstance(parts, list):
        txt = "\n".join(p for p in parts if isinstance(p, str) and p.strip())
        return txt
    # Fallbacks (less common)
    t = content.get("text")
    if isinstance(t, str):
        return t
    t2 = msg_obj.get("text")
    if isinstance(t2, str):
        return t2
    return ""


def _role(msg_obj: Dict[str, Any]) -> str:
    author = (msg_obj or {}).get("author") or {}
    role = author.get("role") or msg_obj.get("role") or "assistant"
    return role


def _timestamp(msg_obj: Dict[str, Any], conv: Dict[str, Any]) -> Tuple[float, str]:
    """
    Prefer message.create_time, then message.update_time, then conv.create_time, else now.
    Returns (seconds_since_epoch, iso_utc).
    """
    sec = None
    for k in ("create_time", "update_time"):
        v = msg_obj.get(k)
        if isinstance(v, (int, float)):
            sec = float(v)
            break
    if sec is None:
        v = conv.get("create_time")
        if isinstance(v, (int, float)):
            sec = float(v)
    if sec is None:
        sec = time.time()
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sec))
    return sec, iso


def _collect_from_mapping(conv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Linearize ChatGPT's mapping graph by time.
    Skip system/empty messages. Keep only user/assistant roles.
    """
    mapping = conv.get("mapping") or {}
    rows: List[Dict[str, Any]] = []
    for node in mapping.values():
        msg = node.get("message")
        if not msg:
            continue
        role = _role(msg)
        if role in SYSTEM_ROLES:
            continue
        text = _message_text(msg)
        if not text.strip():
            continue
        sec, iso = _timestamp(msg, conv)
        # Normalize roles to just 'user' or 'assistant'
        nrole = role if role in ("user", "assistant") else "assistant"
        rows.append(
            {
                "role": nrole,
                "text": text,
                "ts_iso": iso,
                "ts_sec": sec,
            }
        )
    # Stable order: by timestamp, then by role to keep user→assistant pairing when equal
    rows.sort(key=lambda r: (r["ts_sec"], 0 if r["role"] == "user" else 1))
    return rows


def _collect_msgs_loose(conv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fallback if there's no mapping: check 'messages' or 'items'.
    """
    candidates = conv.get("messages") or conv.get("items") or []
    rows: List[Dict[str, Any]] = []
    for msg in candidates:
        role = _role(msg)
        if role in SYSTEM_ROLES:
            continue
        text = _message_text(msg)
        if not text.strip():
            continue
        sec, iso = _timestamp(msg, conv)
        nrole = role if role in ("user", "assistant") else "assistant"
        rows.append(
            {
                "role": nrole,
                "text": text,
                "ts_iso": iso,
                "ts_sec": sec,
            }
        )
    rows.sort(key=lambda r: (r["ts_sec"], 0 if r["role"] == "user" else 1))
    return rows


def _iter_conversations_from_zip(zpath: Path):
    with zipfile.ZipFile(zpath, "r") as zf:
        names = zf.namelist()
        # Preferred file
        if "conversations.json" in names:
            with zf.open("conversations.json") as f:
                raw = f.read().decode("utf-8", errors="ignore")
                data = json.loads(raw)
                if isinstance(data, list):
                    for conv in data:
                        yield conv
                else:
                    for conv in data.get("conversations", []):
                        yield conv
            return
        # Fallback: scan any .json
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            try:
                with zf.open(name) as f:
                    raw = f.read().decode("utf-8", errors="ignore")
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and (
                        "mapping" in obj or "messages" in obj or "items" in obj
                    ):
                        yield obj
            except Exception:
                continue


def _iter_conversations_from_json(jpath: Path):
    raw = jpath.read_text(encoding="utf-8", errors="ignore")
    data = json.loads(raw)
    if isinstance(data, list):
        for conv in data:
            yield conv
    else:
        for conv in data.get("conversations", []):
            yield conv


def parse_export(raw_path: Path, out_dir: Path) -> Tuple[int, int]:
    """
    Parse raw.zip or raw.json → rows.jsonl, threads.json, meta.json
    Returns (num_conversations, num_messages)
    """
    out_rows = out_dir / "rows.jsonl"
    out_threads = out_dir / "threads.json"
    out_meta = out_dir / "meta.json"

    # Start fresh
    if out_rows.exists():
        out_rows.unlink()

    meta: Dict[str, Any] = {}
    threads: Dict[str, List[int]] = {}

    msg_auto = 0
    conv_count = 0

    def emit(conv_id: str, title: str, msgs: List[Dict[str, Any]]):
        nonlocal msg_auto
        ordered: List[int] = []
        for m in msgs:
            text = m["text"]
            msg_id = msg_auto
            msg_auto += 1

            # Append one JSON row per message
            with out_rows.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "msg": msg_id,
                            "conv_id": conv_id,
                            "conv_title": title,
                            "ts": m["ts_iso"],
                            "role": m["role"],
                            "text": text,
                            "has_code": _has_code(text),
                        }
                    )
                    + "\n"
                )

            ordered.append(msg_id)
            meta[str(msg_id)] = {
                "conv_id": conv_id,
                "title": title,
                "len": len(WORD_RE.findall(text.lower())),
                "ts": m["ts_iso"],
                "has_code": _has_code(text),
                "role": m["role"],
            }
        if ordered:
            threads.setdefault(conv_id, []).extend(ordered)

    # Choose iterator based on file type
    if raw_path.suffix.lower() == ".zip":
        conv_iter = _iter_conversations_from_zip(raw_path)
    else:
        conv_iter = _iter_conversations_from_json(raw_path)

    for idx, conv in enumerate(conv_iter, start=1):
        conv_count += 1
        conv_id = str(conv.get("id") or conv.get("conversation_id") or f"c_{idx}")
        title = conv.get("title") or f"Conversation {idx}"
        msgs = _collect_from_mapping(conv) if conv.get("mapping") else _collect_msgs_loose(conv)
        if not msgs:
            continue
        emit(conv_id, title, msgs)

    out_threads.write_text(json.dumps(threads), encoding="utf-8")
    out_meta.write_text(json.dumps(meta), encoding="utf-8")

    return conv_count, len(meta)
