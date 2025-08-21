from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple
import json, math, datetime as dt

LN2 = math.log(2.0)

def _load_rows(ddir: Path):
    rows = []
    with (ddir / "rows.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows

def _load_meta(ddir: Path) -> Dict[str, dict]:
    p = ddir / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def _load_vecs(ddir: Path):
    p = ddir / "vecs.npz"
    if not p.exists():
        return None, None
    import numpy as np
    z = np.load(p)
    return z["ids"], z["vecs"]

def _cos(a, b):
    import numpy as np
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(a.dot(b) / (na * nb))

def build_edges(ddir: Path, same_topic_k: int = 3, same_topic_min_cos: float = 0.60):
    rows = _load_rows(ddir)
    meta = _load_meta(ddir)

    # Map msg_id -> (conv_id, ts, role)
    M: Dict[int, dict] = {}
    for r in rows:
        m = int(r["msg"])
        M[m] = {
            "conv_id": r.get("conv_id"),
            "ts": r.get("ts"),
            "role": r.get("role"),
        }

    edges: List[Dict] = []

    # 1) Reply-chain / adjacency edges within a conversation
    from collections import defaultdict
    by_conv = defaultdict(list)
    for r in rows:
        by_conv[r["conv_id"]].append(r)
    for conv_id, lst in by_conv.items():
        lst.sort(key=lambda x: x.get("ts") or "")
        for i in range(len(lst) - 1):
            a = int(lst[i]["msg"]); b = int(lst[i + 1]["msg"])
            edges.append({"src": a, "dst": b, "w": 2.0, "type": "reply"})

    # 2) Same-topic edges via dense vecs (optional)
    ids, vecs = _load_vecs(ddir)
    if ids is not None:
        import numpy as np
        id_to_idx = {int(i): j for j, i in enumerate(ids.tolist())}
        for conv_id, lst in by_conv.items():
            if same_topic_k <= 0:
                continue
            # consider small local candidate pool: the conversation itself
            idxs = [id_to_idx[int(r["msg"])] for r in lst if int(r["msg"]) in id_to_idx]
            for j in idxs:
                v = vecs[j]
                # quick top-k by cosine against others in the same conversation
                sims = []
                for k in idxs:
                    if k == j: continue
                    s = _cos(v, vecs[k])
                    if s >= same_topic_min_cos:
                        sims.append((k, s))
                sims.sort(key=lambda t: t[1], reverse=True)
                for k, s in sims[:same_topic_k]:
                    edges.append({"src": int(ids[j]), "dst": int(ids[k]), "w": float(1.0 + s), "type": "same_topic"})

    # Write edges
    out = ddir / "edges.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e) + "\n")
    return {"edges_path": str(out)}

def build_pagerank(ddir: Path, alpha: float = 0.15, half_life_days: float = 180.0):
    try:
        import networkx as nx
    except ImportError as e:
        raise RuntimeError("networkx is required for /pr/build. Install in your venv: pip install networkx") from e

    # Load edges
    edges = []
    with (ddir / "edges.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                edges.append((int(e["src"]), int(e["dst"]), float(e.get("w", 1.0))))
            except Exception:
                continue

    G = nx.DiGraph()
    for s, d, w in edges:
        G.add_edge(s, d, weight=w)

    # Personalization/recency (teleport vector)
    meta = json.loads((ddir / "meta.json").read_text(encoding="utf-8"))
    def recency_boost(ts: str) -> float:
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
        age_days = max(0.0, (dt.datetime.now(dt.timezone.utc).timestamp() - t) / 86400.0)
        return math.exp(-LN2 * age_days / max(half_life_days, 1e-3))

    p = {}
    for k, v in meta.items():
        msg = int(k)
        b = 1e-6
        b += recency_boost(v.get("ts") or "")
        if (v.get("role") or "").lower() == "assistant":
            b += 0.05
        if v.get("has_code"):
            b += 0.05
        p[msg] = b

    # Normalize personalization vector
    s = sum(p.values()) or 1.0
    p = {k: v / s for k, v in p.items() if k in G}

    # networkx uses alpha = damping (follow links). Our API alpha = teleport prob.
    nx_alpha = 1.0 - max(0.0, min(alpha, 1.0))
    pr = nx.pagerank(G, alpha=nx_alpha, personalization=p, weight="weight")

    # Save
    (ddir / "pr_global.json").write_text(json.dumps({str(k): float(v) for k, v in pr.items()}), encoding="utf-8")
    return {"nodes": len(G), "edges": len(edges), "alpha": alpha, "half_life_days": half_life_days, "out": str(ddir / "pr_global.json")}
