from __future__ import annotations
from pathlib import Path
import json, math, re
from collections import defaultdict, Counter

# simple, code-aware tokenizer
_CAMEL = re.compile(r'(?<!^)(?=[A-Z])')
_WORDS = re.compile(r"[a-zA-Z0-9_]+")

STOP = set("""
a an and are as at be by for from has have i in is it its of on or that the to was were will with you your
""".split())

def split_ident(tok: str):
    # snake_case + camelCase splits
    parts = tok.split('_')
    res = []
    for p in parts:
        # split camel: "myHTTPServer" -> ["my", "HTTP", "Server"]
        res.extend(_CAMEL.sub(' ', p).split())
    return [r for r in res if r]

def tokenize(text: str):
    """Lowercase, wordish chars, keep identifiers split by _ and camel, drop stopwords."""
    if not text:
        return []
    text = text.strip().lower()
    toks = _WORDS.findall(text)
    out: list[str] = []
    for t in toks:
        if t in STOP:
            continue
        out.append(t)
        # extra splits (mostly effective on snake_case after .lower())
        for part in split_ident(t):
            p = part.lower()
            if p != t and p not in STOP:
                out.append(p)
    return out

# ---------------- BM25 core ----------------

def build_bm25(ddir: Path, k1: float = 1.2, b: float = 0.75):
    """
    Build a light BM25 inverted index over rows.jsonl:
      - index.json : { term: [[doc_id, tf], ...] }
      - idf.json   : { term: idf }
      - doclen.json: { doc_id: length_in_tokens }
      - stats.json : { terms, docs, avg_len, k1, b }
    """
    rows_path = ddir / "rows.jsonl"
    if not rows_path.exists():
        raise FileNotFoundError("rows.jsonl not found. Run /parse first.")

    postings: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    doclen: dict[int, int] = {}
    docs = 0

    with rows_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            doc_id = int(row["msg"])
            text = row.get("text") or ""
            toks = tokenize(text)
            if not toks:
                doclen[doc_id] = 0
                docs += 1
                continue
            cnt = Counter(toks)
            for term, tf in cnt.items():
                postings[term][doc_id] += int(tf)
            doclen[doc_id] = int(sum(cnt.values()))
            docs += 1

    if docs == 0:
        raise RuntimeError("No documents found to index.")

    # idf
    N = docs
    idf: dict[str, float] = {}
    for term, plist in postings.items():
        df = len(plist)
        # BM25+ style idf (robust)
        idf[term] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

    # avg doc len
    avg_len = (sum(doclen.values()) / max(1, len(doclen)))

    # Write files
    # index.json as compact postings: { term: [[doc, tf], ...] }
    index_path = ddir / "index.json"
    with index_path.open("w", encoding="utf-8") as f:
        json.dump({t: [[int(d), int(tf)] for d, tf in plist.items()]
                   for t, plist in postings.items()}, f, ensure_ascii=False)

    (ddir / "idf.json").write_text(json.dumps(idf), encoding="utf-8")
    (ddir / "doclen.json").write_text(json.dumps({str(d): int(L) for d, L in doclen.items()}), encoding="utf-8")
    (ddir / "stats.json").write_text(json.dumps({
        "terms": len(idf),
        "docs": int(N),
        "avg_len": float(avg_len),
        "k1": float(k1),
        "b": float(b),
    }), encoding="utf-8")

    return {"terms": len(idf), "docs": int(N), "avg_len": float(avg_len)}

def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def bm25_search(ddir: Path, query: str, topk: int = 10, k1: float | None = None, b: float | None = None):
    """
    Score docs with BM25. Returns list[ {msg, score, conv_id, title, role, ts} ].
    Requires: index.json, idf.json, doclen.json, stats.json, meta.json.
    """
    idx_path = ddir / "index.json"
    idf_path = ddir / "idf.json"
    dl_path  = ddir / "doclen.json"
    st_path  = ddir / "stats.json"
    meta_path= ddir / "meta.json"

    if not (idx_path.exists() and idf_path.exists() and dl_path.exists() and st_path.exists() and meta_path.exists()):
        raise FileNotFoundError("Missing BM25 files. Build index first.")

    index = _load_json(idx_path)          # term -> [[doc, tf], ...]
    idf   = _load_json(idf_path)          # term -> idf
    doclen= {int(k): int(v) for k, v in _load_json(dl_path).items()}
    stats = _load_json(st_path)
    meta  = _load_json(meta_path)

    avg_len = float(stats.get("avg_len", 1.0))
    K1 = float(k1 if k1 is not None else stats.get("k1", 1.2))
    B  = float(b  if b  is not None else stats.get("b", 0.75))

    q_terms = tokenize(query)
    if not q_terms:
        return []

    scores: dict[int, float] = defaultdict(float)
    seen_docs: set[int] = set()

    for t in q_terms:
        plist = index.get(t)
        if not plist:
            continue
        w = float(idf.get(t, 0.0))
        if w <= 0:
            continue
        for doc_id, tf in plist:
            dl = doclen.get(int(doc_id), 0)
            denom = tf + K1 * (1 - B + B * (dl / max(1.0, avg_len)))
            s = w * ((tf * (K1 + 1.0)) / max(1e-9, denom))
            scores[int(doc_id)] += s
            seen_docs.add(int(doc_id))

    if not scores:
        return []

    ranked = sorted(seen_docs, key=lambda d: scores[d], reverse=True)[:topk]
    out = []
    for doc_id in ranked:
        m = meta.get(str(doc_id), {})
        out.append({
            "msg": int(doc_id),
            "score": float(scores[doc_id]),
            "conv_id": m.get("conv_id"),
            "title": m.get("title"),
            "role": m.get("role"),
            "ts": m.get("ts"),
        })
    return out
