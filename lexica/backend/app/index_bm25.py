# backend/app/index_bm25.py
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
        res.extend(_CAMEL.sub(' ', p).split())
    return [r for r in res if r]

def tokenize(text: str):
    if not text: return []
    text = text.lower()
    toks = _WORDS.findall(text)
    out = []
    for t in toks:
        if t in STOP: 
            continue
        out.append(t)
        # add sub-tokens for identifiers (optional)
        for sub in split_ident(t):
            if sub != t and sub not in STOP:
                out.append(sub.lower())
    return out

def build_bm25(ddir: Path, k1=1.2, b=0.75):
    rows_path = ddir / "rows.jsonl"
    assert rows_path.exists(), f"missing {rows_path}"
    postings: dict[str, list[tuple[int,int]]] = defaultdict(list)
    df: Counter[str] = Counter()
    doc_len: dict[int, int] = {}
    N = 0

    with rows_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            msg_id = int(row["msg"])
            toks = tokenize(row.get("text",""))
            N += 1
            doc_len[msg_id] = len(toks)
            tf = Counter(toks)
            for term, c in tf.items():
                postings[term].append((msg_id, c))
            df.update(tf.keys())

    avg_len = (sum(doc_len.values()) / max(N,1))
    idf = {}
    # BM25+ style idf that avoids negatives
    for term, d in df.items():
        idf[term] = math.log(1 + ((N - d + 0.5)/(d + 0.5)))

    # write artifacts
    (ddir / "index.json").write_text(
        json.dumps({t: [{"msg": m, "tf": tf} for (m, tf) in pl] for t, pl in postings.items()}), 
        encoding="utf-8"
    )
    (ddir / "idf.json").write_text(json.dumps(idf), encoding="utf-8")
    (ddir / "stats.json").write_text(json.dumps({"N": N, "avg_len": avg_len, "k1": k1, "b": b}), encoding="utf-8")
    (ddir / "doclen.json").write_text(json.dumps({str(k): v for k, v in doc_len.items()}), encoding="utf-8")

    return {"terms": len(postings), "docs": N, "avg_len": avg_len}

def bm25_search(ddir: Path, query: str, topk: int = 20, k1=1.2, b=0.75):
    if not query.strip(): return []

    index = json.loads((ddir / "index.json").read_text(encoding="utf-8"))
    idf = json.loads((ddir / "idf.json").read_text(encoding="utf-8"))
    stats = json.loads((ddir / "stats.json").read_text(encoding="utf-8"))
    doclen = json.loads((ddir / "doclen.json").read_text(encoding="utf-8"))
    meta = json.loads((ddir / "meta.json").read_text(encoding="utf-8"))

    N = stats["N"]; avg_len = stats["avg_len"]
    if "k1" in stats: k1 = stats["k1"]
    if "b" in stats: b = stats["b"]

    q_terms = tokenize(query)
    scores: dict[int, float] = defaultdict(float)

    for qt in q_terms:
        plist = index.get(qt)
        if not plist: 
            continue
        term_idf = idf.get(qt, 0.0)
        for entry in plist:
            m = int(entry["msg"]); tf = int(entry["tf"])
            dl = doclen.get(str(m)) or doclen.get(m) or 0
            if dl <= 0: 
                continue
            denom = tf + k1*(1 - b + b*(dl/avg_len))
            scores[m] += term_idf * ((tf*(k1+1)) / max(denom, 1e-9))

    # sort & package
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:topk]
    out = []
    for msg_id, sc in ranked:
        mmeta = meta.get(str(msg_id)) or {}
        out.append({
            "msg": msg_id,
            "score": sc,
            "conv_id": mmeta.get("conv_id"),
            "title": mmeta.get("title"),
            "role": mmeta.get("role"),
            "ts": mmeta.get("ts"),
        })
    return out
