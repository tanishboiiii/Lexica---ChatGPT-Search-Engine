from __future__ import annotations
from pathlib import Path
import json, math, time, datetime as dt
from typing import Dict, List
import numpy as np

from .index_bm25 import bm25_search
from .semantic import dense_search  # will be used if vecs.npz exists

HALF_LIFE_DAYS = 90.0
LN2 = math.log(2.0)

def _z_norm(scores: Dict[int, float], ids: List[int]) -> Dict[int, float]:
    arr = np.array([scores.get(i, 0.0) for i in ids], dtype=float)
    if arr.size == 0:
        return {i: 0.0 for i in ids}
    mu, sd = float(arr.mean()), float(arr.std())
    if sd < 1e-9:
        return {i: 0.0 for i in ids}
    z = (arr - mu) / (sd + 1e-9)
    return {i: float(v) for i, v in zip(ids, z)}

def _freshness(ts_iso: str, now: float) -> float:
    try:
        t = dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0
    age_days = max(0.0, (now - t) / 86400.0)
    return float(math.exp(-LN2 * age_days / HALF_LIFE_DAYS))

def _load_pr_global(ddir: Path) -> Dict[int, float]:
    p = ddir / "pr_global.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {int(k): float(v) for k, v in data.items()}
    except Exception:
        return {}

def _load_edges(ddir: Path):
    p = ddir / "edges.jsonl"
    if not p.exists():
        return []
    edges = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                src = int(obj.get("src"))
                dst = int(obj.get("dst"))
                w = float(obj.get("w", 1.0))
                edges.append((src, dst, w))
            except Exception:
                continue
    return edges

def _mini_ppr(candidate_ids: List[int],
              edges,
              seed_weights: Dict[int, float],
              alpha: float = 0.2,
              iters: int = 20) -> Dict[int, float]:
    if not candidate_ids or not edges:
        return {i: 0.0 for i in candidate_ids}

    idx = {msg: k for k, msg in enumerate(candidate_ids)}
    N = len(candidate_ids)

    col_w = np.zeros(N, dtype=float)
    rows, cols, vals = [], [], []
    for s, d, w in edges:
        if s in idx and d in idx:
            i, j = idx[d], idx[s]
            rows.append(i); cols.append(j); vals.append(float(w))
            col_w[j] += float(w)
    if not vals or float(np.sum(col_w)) == 0.0:
        return {i: 0.0 for i in candidate_ids}

    vals = np.array(vals, dtype=float)
    col_w[col_w == 0.0] = 1.0
    vals /= np.take(col_w, cols)

    A = (np.array(rows, int), np.array(cols, int), vals)

    v = np.array([max(0.0, seed_weights.get(i, 0.0)) for i in candidate_ids], dtype=float)
    if v.sum() <= 0:
        v[:] = 1.0
    v /= v.sum()

    r = v.copy()
    for _ in range(iters):
        Ar = np.zeros(N, dtype=float)
        Ar[A[0]] += A[2] * r[A[1]]
        r = alpha * v + (1 - alpha) * Ar

    return {i: float(x) for i, x in zip(candidate_ids, r)}

def hybrid_search(ddir: Path, q: str, topk: int = 10, explain: bool = False):
    now = time.time()

    # ---- First-stage recall
    bm = bm25_search(ddir, q, topk=400)
    bm_map = {int(r["msg"]): float(r["score"]) for r in bm}
    id_meta = {int(r["msg"]): r for r in bm}

    # semantic is optional
    cos_map, dense_meta = {}, {}
    try:
        dense = dense_search(ddir, q, topk=400)
        cos_map = {int(r["msg"]): float(r["score"]) for r in dense}
        for r in dense:
            id_meta.setdefault(int(r["msg"]), r)
            dense_meta[int(r["msg"])] = r
    except Exception:
        dense = []

    cand_ids = list({*bm_map.keys(), *cos_map.keys()})
    if not cand_ids:
        return []

    # ---- Signals
    pr_global = _load_pr_global(ddir)
    edges = _load_edges(ddir)

    # seed for query-biased PPR
    beta, gamma = 1.0, 1.0
    seeds = {}
    for i in cand_ids:
        b = max(0.0, bm_map.get(i, 0.0))
        c = max(0.0, cos_map.get(i, 0.0))
        seeds[i] = (b ** beta) * ((c if c > 0 else b) ** gamma)

    ppr_raw = _mini_ppr(cand_ids, edges, seeds) if edges else {i: 0.0 for i in cand_ids}

    fresh = {}
    prior = {}
    for i in cand_ids:
        meta = id_meta.get(i, {})
        ts = meta.get("ts") or ""
        role = (meta.get("role") or "").lower()
        has_code = bool(meta.get("has_code", False))
        snippet = meta.get("snippet") or meta.get("text") or ""

        fresh[i] = _freshness(ts, now)
        prior[i] = (0.30 if role == "assistant" else 0.0) \
                 + (0.40 if has_code else 0.0) \
                 + (0.30 * min(len(snippet), 800) / 800.0)

    bm_z    = _z_norm(bm_map,    cand_ids)
    cos_z   = _z_norm(cos_map,   cand_ids) if cos_map else {i: 0.0 for i in cand_ids}
    prg_z   = _z_norm(pr_global, cand_ids) if pr_global else {i: 0.0 for i in cand_ids}
    ppr_z   = _z_norm(ppr_raw,   cand_ids) if ppr_raw else {i: 0.0 for i in cand_ids}

    W_BM25 = 1.00
    W_SEM  = 0.55
    W_AUTH = 0.20
    W_FRSH = 0.10
    W_PRG  = 0.20
    W_PPR  = 0.25

    fused = {}
    for i in cand_ids:
        fused[i] = (
            W_BM25 * bm_z.get(i, 0.0) +
            W_SEM  * cos_z.get(i, 0.0) +
            W_AUTH * prior.get(i, 0.0) +
            W_FRSH * fresh.get(i, 0.0) +
            W_PRG  * prg_z.get(i, 0.0) +
            W_PPR  * ppr_z.get(i, 0.0)
        )

    ranked = sorted(cand_ids, key=lambda x: fused[x], reverse=True)[:topk]
    out = []
    for i in ranked:
        meta = id_meta.get(i, {})
        rec = {
            "msg": i,
            "score": fused[i],
            "conv_id": meta.get("conv_id"),
            "title": meta.get("title"),
            "role": meta.get("role"),
            "ts": meta.get("ts"),
            "snippet": meta.get("snippet") or meta.get("text"),
        }
        if explain:
            rec.update({
                "bm25": bm_map.get(i, 0.0),
                "cos": cos_map.get(i, 0.0),
                "pr_global": pr_global.get(i, 0.0),
                "ppr": ppr_raw.get(i, 0.0),
                "fresh": fresh.get(i, 0.0),
            })
        out.append(rec)
    return out
