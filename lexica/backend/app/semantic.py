from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import re

# Very light-weight char-trigram hashing for “semantic nudging”
DIMS = 1024
WORD = re.compile(r"\S+")

def _char_trigrams(s: str):
    s = " " + s.lower() + " "
    return [s[i:i+3] for i in range(len(s)-2)]

def _embed(text: str, dims: int = DIMS) -> np.ndarray:
    v = np.zeros(dims, dtype=np.float32)
    for tri in _char_trigrams(text):
        h = (hash(tri) % dims + dims) % dims
        v[h] += 1.0
    n = np.linalg.norm(v)
    if n > 0: v /= n
    return v

def build_vecs(ddir: Path, dims: int = DIMS):
    rows_path = ddir / "rows.jsonl"
    assert rows_path.exists(), "rows.jsonl not found. Run /parse first."

    ids = []
    vecs = []

    with rows_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            msg = int(row["msg"])
            txt = row.get("text") or ""
            ids.append(msg)
            vecs.append(_embed(txt, dims))

    ids = np.array(ids, dtype=np.int64)
    vecs = np.stack(vecs, axis=0).astype(np.float32)

    np.savez_compressed(ddir / "vecs.npz", ids=ids, vecs=vecs)
    (ddir / "vec_meta.json").write_text(json.dumps({"dims": dims, "count": int(ids.shape[0])}), encoding="utf-8")
    return {"count": int(ids.shape[0]), "dims": dims, "path": str(ddir / "vecs.npz")}

def dense_search(ddir: Path, query: str, topk: int = 10):
    zpath = ddir / "vecs.npz"
    assert zpath.exists(), "vecs.npz not found. Build with /index/vecs"

    z = np.load(zpath)
    ids, mat = z["ids"], z["vecs"]
    qv = _embed(query, mat.shape[1])

    # cosine with normalized rows = dot
    sims = (mat @ qv).astype(np.float32)
    top = np.argsort(-sims)[:topk]

    meta = json.loads((ddir / "meta.json").read_text(encoding="utf-8"))
    out = []
    for j in top:
        msg = int(ids[j]); sc = float(sims[j])
        m = meta.get(str(msg)) or {}
        out.append({
            "msg": msg,
            "score": sc,
            "conv_id": m.get("conv_id"),
            "title": m.get("title"),
            "role": m.get("role"),
            "ts": m.get("ts"),
            "snippet": (m.get("snippet") or m.get("text")),
        })
    return out
