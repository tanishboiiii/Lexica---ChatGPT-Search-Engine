from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import tempfile, uuid, shutil, logging

# ----- config -----
TMP_ROOT = Path(tempfile.gettempdir()) / "lexica"    # e.g., C:\Users\<you>\AppData\Local\Temp\lexica
TMP_ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTS = (".zip", ".json")
MAX_UPLOAD_MB = 300
PORT = 8000
# ------------------

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Lexica Upload API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def new_dataset_id() -> str:
    return uuid.uuid4().hex[:10]

def dataset_dir(ds_id: str) -> Path:
    p = TMP_ROOT / ds_id
    p.mkdir(parents=True, exist_ok=True)
    return p

@app.get("/ping")
def ping():
    return {"ok": True}

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
        with open(out_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as e:
        log.exception("Upload save failed")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}") from e
    finally:
        await file.close()

    log.info(f"[upload] dataset_id={ds_id} saved → {out_path}")
    return JSONResponse({"ok": True, "dataset_id": ds_id, "path": str(out_path)})
