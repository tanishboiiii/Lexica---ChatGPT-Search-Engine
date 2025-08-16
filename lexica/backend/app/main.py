from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import tempfile, uuid, shutil, logging, os

from .parse import parse_export
from .index_bm25 import build_bm25, bm25_search
from .search import search_bm25_with_snippets, get_conversation


# ------------------ Config ------------------
# Single storage root (override with LEXICA_DATA_DIR)
DATA_ROOT = Path(os.environ.get("LEXICA_DATA_DIR", Path(tempfile.gettempdir()) / "lexica"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = (".zip", ".json")
MAX_UPLOAD_MB = 300

log = logging.getLogger("uvicorn.error")


def dataset_dir(ds_id: str) -> Path:
    p = DATA_ROOT / ds_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_dataset_id() -> str:
    return uuid.uuid4().hex[:10]


# ------------------ App ------------------
app = FastAPI(title="Lexica Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",  # dev-friendly; tighten in prod
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------ Health ------------------
@app.get("/ping")
def ping():
    return {"ok": True}


# ------------------ Upload ------------------
@app.post("/upload")
async def upload_dataset(request: Request, file: UploadFile = File(...)):
    # validate extension
    name = (file.filename or "").lower()
    if not name.endswith(ALLOWED_EXTS):
        raise HTTPException(status_code=400, detail="Upload a ChatGPT export .zip or conversations.json")

    # best-effort size guard (browser may not send content-length)
    cl = request.headers.get("content-length")
    if cl and int(cl) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large (> {MAX_UPLOAD_MB} MB)")

    ds_id = new_dataset_id()
    out_ext = ".zip" if name.endswith(".zip") else ".json"
    out_path = dataset_dir(ds_id) / f"raw{out_ext}"

    try:
        with out_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as e:
        log.exception("Upload save failed")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}") from e
    finally:
        await file.close()

    log.info(f"[upload] dataset_id={ds_id} saved → {out_path}")
    return JSONResponse({"ok": True, "dataset_id": ds_id, "path": str(out_path)})


# ------------------ Dataset utilities ------------------
@app.get("/datasets/{dataset_id}/ls")
def list_dataset(dataset_id: str):
    p = dataset_dir(dataset_id)
    if not p.exists():
        raise HTTPException(404, "Dataset not found")
    items = []
    for f in p.iterdir():
        if f.is_file():
            stat = f.stat()
            items.append({"name": f.name, "size": stat.st_size})
    return {"path": str(p), "items": items}


@app.get("/datasets/{dataset_id}/raw")
def download_raw(dataset_id: str):
    p = dataset_dir(dataset_id)
    raw_zip = p / "raw.zip"
    raw_json = p / "raw.json"
    raw = raw_zip if raw_zip.exists() else raw_json
    if not raw.exists():
        raise HTTPException(404, "Raw file not found")
    return FileResponse(raw, filename=raw.name)


# ------------------ Parse ------------------
@app.post("/datasets/{dataset_id}/parse")
def parse_dataset(dataset_id: str):
    ddir = dataset_dir(dataset_id)
    raw_zip = ddir / "raw.zip"
    raw_json = ddir / "raw.json"
    raw = raw_zip if raw_zip.exists() else raw_json
    if not raw.exists():
        raise HTTPException(status_code=404, detail="raw.zip or raw.json not found in dataset directory")

    convs, msgs = parse_export(raw, ddir)
    return {"ok": True, "conversations": convs, "messages": msgs, "dir": str(ddir)}


# ------------------ Index (BM25) ------------------
@app.post("/datasets/{dataset_id}/index/bm25")
def build_index_bm25(dataset_id: str):
    ddir = dataset_dir(dataset_id)
    if not (ddir / "rows.jsonl").exists():
        raise HTTPException(400, "rows.jsonl not found. Run /parse first.")
    stats = build_bm25(ddir)
    return {"ok": True, **stats, "dir": str(ddir)}


# ------------------ Search ------------------
# Single endpoint with a 'mode' switch:
#   mode="basic"  -> raw BM25
#   mode="snippets" (default) -> BM25 + snippet building + filters
@app.get("/datasets/{dataset_id}/search")
def search_dataset(
    dataset_id: str,
    q: str = Query(..., min_length=1),
    k: int = 10,
    role: str | None = None,          # 'user' | 'assistant'
    has_code: bool | None = None,     # 'true'/'false'
    after: str | None = None,         # 'YYYY-MM-DD'
    before: str | None = None,        # 'YYYY-MM-DD'
    conv_id: str | None = None,
    mode: str = Query("snippets", regex="^(snippets|basic)$"),
):
    ddir = dataset_dir(dataset_id)

    # sanity checks
    required = ["index.json", "idf.json", "stats.json", "doclen.json", "meta.json"]
    if mode == "snippets":
        required.append("rows.jsonl")
    for need in required:
        if not (ddir / need).exists():
            raise HTTPException(400, f"Missing {need}. Build index first.")

    # normalize has_code if provided
    if has_code is not None and not isinstance(has_code, bool):
        has_code = True if str(has_code).lower() == "true" else False

    if mode == "basic":
        results = bm25_search(ddir, q, topk=k)
        return {"ok": True, "q": q, "k": k, "results": results, "mode": mode}

    # default: snippets mode with filters
    results = search_bm25_with_snippets(
        ddir, q, k=k, role=role, has_code=has_code, after_iso=after, before_iso=before, conv_id=conv_id
    )
    return {"ok": True, "q": q, "k": k, "results": results, "mode": mode}


@app.get("/datasets/{dataset_id}/conversation/{conv_id}")
def fetch_conversation(dataset_id: str, conv_id: str, center_msg: int | None = None, window: int = 15):
    ddir = dataset_dir(dataset_id)
    return get_conversation(ddir, conv_id, center_msg=center_msg, window=window)
