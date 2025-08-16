from __future__ import annotations
from pathlib import Path
import json, math, re, datetime as dt

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")  # same-ish tokenizer used when indexing

def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def tokenize(text: str):
    return [t.lower() for t in TOKEN_RE.findall(text)]

def bm25_score(query_terms, postings, idf, doclen, N, avg_len, k1=1.2, b=0.75):
    # Accumulate scores only on docs that contain at least one query term
    scores = {}
    for term in query_terms:
        if term not in idf or term not in postings:
            continue
        w = idf[term]
        for hit in postings[term]:
            d = hit["msg"]
            tf = hit["tf"]
            dl = doclen.get(str(d)) or doclen.get(d) or 0
            denom = tf + k1 * (1 - b + b * (dl / (avg_len or 1.0)))
            add = w * (tf * (k1 + 1)) / (denom or 1.0)
            scores[d] = scores.get(d, 0.0) + add
    return scores

def _load_rows_list(ddir: Path):
    # Small helper: load all rows.jsonl once (17MB in your case) → quick random access
    # If you prefer streaming, you can read by line number each time.
    rows_path = ddir / "rows.jsonl"
    out = []
    with rows_path.open("r", encoding="utf-8") as f:
        for line in f:
            out.append(json.loads(line))
    return out

def _first_hit_offsets(text: str, terms):
    # find earliest index of any term for centering the snippet
    lower = text.lower()
    best = None
    for t in terms:
        i = lower.find(t)
        if i != -1 and (best is None or i < best):
            best = i
    return best if best is not None else 0

def _make_snippet(text: str, terms, width=220):
    if not text:
        return ""
    pos = _first_hit_offsets(text, terms)
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    chunk = text[start:end]
    # simple highlight
    for t in sorted(set(terms), key=len, reverse=True):
        chunk = re.sub(fr"(?i)\b({re.escape(t)})\b", r"<mark>\1</mark>", chunk)
    if start > 0:   chunk = "… " + chunk
    if end < len(text): chunk = chunk + " …"
    return chunk

def _bool_has_code(row):
    return bool(row.get("has_code"))

def _role(row):
    return row.get("role")

def _ts(row):
    t = row.get("ts")
    # rows.jsonl ts is ISOZ per your sample; fallback to epoch seconds if needed
    try:
        return dt.datetime.fromisoformat(t.replace("Z","+00:00"))
    except Exception:
        try:
            return dt.datetime.utcfromtimestamp(float(t))
        except Exception:
            return None

def _freshness_boost(row, now=None):
    # mild exponential decay: newer → small positive boost
    now = now or dt.datetime.now(dt.timezone.utc)
    ts = _ts(row)
    if not ts:
        return 0.0
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    # scale: 0.0 (today) → ~0.25 (1 day) → down to almost 0 by ~180 days
    return 0.25 * math.exp(-age_days / 14.0)

def _code_boost(row):
    return 0.2 if _bool_has_code(row) else 0.0

def search_bm25_with_snippets(
    ddir: Path,
    q: str,
    k: int = 10,
    role: str | None = None,          # 'user' | 'assistant'
    has_code: bool | None = None,     # True/False
    after_iso: str | None = None,     # 'YYYY-MM-DD'
    before_iso: str | None = None,    # 'YYYY-MM-DD'
    conv_id: str | None = None
):
    index = load_json(ddir / "index.json")
    idf   = load_json(ddir / "idf.json")
    meta  = load_json(ddir / "meta.json")
    doclen= load_json(ddir / "doclen.json")
    stats = None
    stats_path = ddir / "stats.json"
    if stats_path.exists():
        stats = load_json(stats_path)
        N = stats.get("N") or len(doclen)
        avg_len = stats.get("avg_len")
    else:
        N = len(doclen)
        avg_len = sum(doclen.values())/max(1,len(doclen))

    rows = _load_rows_list(ddir)

    q_terms = tokenize(q)
    scores = bm25_score(q_terms, index, idf, doclen, N, avg_len)

    # collect candidates with metadata
    cands = []
    for msg_id_str, score in scores.items():
        # msg ids may be ints or strings; normalize
        msg_id = int(msg_id_str)
        row = rows[msg_id] if msg_id < len(rows) else None
        if not row:
            continue

        # filters
        if role and _role(row) != role:
            continue
        if has_code is not None and _bool_has_code(row) != has_code:
            continue
        if conv_id and row.get("conv_id") != conv_id:
            continue
        if after_iso:
            try:
                if _ts(row) and _ts(row) < dt.datetime.fromisoformat(after_iso).replace(tzinfo=dt.timezone.utc):
                    continue
            except Exception:
                pass
        if before_iso:
            try:
                if _ts(row) and _ts(row) > dt.datetime.fromisoformat(before_iso).replace(tzinfo=dt.timezone.utc):
                    continue
            except Exception:
                pass

        # simple, fast boosts (kept small so BM25 still dominates)
        boosted = score + _freshness_boost(row) + _code_boost(row)

        cands.append({
            "msg": msg_id,
            "score": boosted,
            "raw_score": score,
            "conv_id": row.get("conv_id"),
            "title": row.get("conv_title") or row.get("title"),
            "role": row.get("role"),
            "ts": row.get("ts"),
            "snippet": _make_snippet(row.get("text") or "", q_terms, width=260),
        })

    # sort and top-k
    cands.sort(key=lambda x: x["score"], reverse=True)
    return cands[:k]

def get_conversation(ddir: Path, conv_id: str, center_msg: int | None = None, window: int = 15):
    threads = load_json(ddir / "threads.json")   # conv_id -> [msg,...]
    meta    = load_json(ddir / "meta.json")      # msg -> {...}
    rows    = _load_rows_list(ddir)

    if conv_id not in threads:
        return {"ok": False, "error": "conv_id not found"}

    msg_ids = threads[conv_id]
    items = []
    for m in msg_ids:
        r = rows[m]
        items.append({
            "msg": m,
            "role": r.get("role"),
            "text": r.get("text"),
            "ts": r.get("ts"),
            "has_code": r.get("has_code")
        })

    # if center_msg provided, trim to a window around it for quick viewer loads
    if center_msg is not None and center_msg in msg_ids:
        i = msg_ids.index(center_msg)
        lo = max(0, i - window)
        hi = min(len(msg_ids), i + window + 1)
        items = items[lo:hi]

    title = meta.get(str(msg_ids[0]), {}).get("conv_title") or meta.get(str(msg_ids[0]), {}).get("title")
    return {"ok": True, "conv_id": conv_id, "title": title, "messages": items}
