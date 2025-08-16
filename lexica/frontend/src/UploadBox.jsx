import React, { useRef, useState } from "react"

const API_BASE = "http://localhost:8000"

export default function UploadBox({ onUploaded }) {
  const fileRef = useRef(null)
  const [progress, setProgress] = useState(0) // 0–100 (upload only)
  const [phase, setPhase] = useState("idle") // idle|uploading|parsing|indexing|done|error
  const [datasetId, setDatasetId] = useState(null)
  const [log, setLog] = useState([])
  const [err, setErr] = useState("")

  function push(msg) {
    setLog((l) => [...l, msg])
  }

  async function handleParseAndIndex(ds) {
    // Parse
    setPhase("parsing")
    push("Parsing export …")
    let res = await fetch(`${API_BASE}/datasets/${ds}/parse`, {
      method: "POST",
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Parse failed: ${res.status} ${text}`)
    }
    const parsed = await res.json()
    push(
      `Parsed ${parsed.messages} messages across ${parsed.conversations} conversations.`
    )

    // Build BM25
    setPhase("indexing")
    push("Building BM25 index …")
    res = await fetch(`${API_BASE}/datasets/${ds}/index/bm25`, {
      method: "POST",
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Indexing failed: ${res.status} ${text}`)
    }
    const stats = await res.json()
    push(
      `Index built: ${stats.docs} docs, ${stats.terms} terms, avg_len=${
        stats.avg_len?.toFixed?.(2) ?? stats.avg_len
      }`
    )

    setPhase("done")
    push("Dataset ready ✔")
    // 🔔 Only signal the app once everything is ready to search
    onUploaded?.(ds)
  }

  async function handleUpload(file) {
    setErr("")
    setLog([])
    setDatasetId(null)
    setProgress(0)
    setPhase("uploading")
    push(`Uploading ${file.name} …`)

    // Use XHR to get upload progress (fetch doesn't expose it)
    const form = new FormData()
    form.append("file", file)

    const xhr = new XMLHttpRequest()
    const url = `${API_BASE}/upload`

    const uploadPromise = new Promise((resolve, reject) => {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          setProgress(Math.round((e.loaded / e.total) * 100))
        }
      }
      xhr.onreadystatechange = () => {
        if (xhr.readyState === 4) {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText))
            } catch (e) {
              reject(new Error("Invalid JSON from /upload"))
            }
          } else {
            reject(
              new Error(`Upload failed: ${xhr.status} ${xhr.responseText}`)
            )
          }
        }
      }
      xhr.open("POST", url, true)
      xhr.send(form)
    })

    try {
      const resp = await uploadPromise
      const ds = resp.dataset_id
      setDatasetId(ds)
      push(`Saved to server as dataset ${ds}.`)
      // Immediately continue with parse + index
      await handleParseAndIndex(ds)
    } catch (e) {
      console.error(e)
      setPhase("error")
      setErr(String(e.message || e))
      push("❌ Upload or processing failed.")
    }
  }

  function onPickFile(e) {
    const f = e.target.files?.[0]
    if (!f) return
    if (!/\.(zip|json)$/i.test(f.name)) {
      setErr("Please select a .zip or conversations.json file.")
      return
    }
    handleUpload(f)
  }

  function onDrop(e) {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f) handleUpload(f)
  }

  function onDragOver(e) {
    e.preventDefault()
  }

  function reset() {
    setProgress(0)
    setPhase("idle")
    setDatasetId(null)
    setLog([])
    setErr("")
    if (fileRef.current) fileRef.current.value = ""
  }

  const busy =
    phase === "uploading" || phase === "parsing" || phase === "indexing"

  return (
    <div className="uploadbox">
      <div
        className="dropzone"
        onDrop={onDrop}
        onDragOver={onDragOver}
        style={{
          border: "1px dashed #bbb",
          padding: 16,
          borderRadius: 8,
          background: "#fafafa",
        }}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip,application/json,.json"
          onChange={onPickFile}
          disabled={busy}
        />
        <div className="muted" style={{ marginTop: 6 }}>
          Drag & drop or choose your <code>conversations.json</code> or exported{" "}
          <code>.zip</code>.
        </div>
      </div>

      {phase === "uploading" && (
        <div style={{ marginTop: 10 }}>
          <div className="muted">Uploading… {progress}%</div>
          <div style={{ height: 8, background: "#eee", borderRadius: 6 }}>
            <div
              style={{
                width: `${progress}%`,
                height: 8,
                background: "#000",
                borderRadius: 6,
                transition: "width 120ms linear",
              }}
            />
          </div>
        </div>
      )}

      {datasetId && (
        <div className="muted" style={{ marginTop: 10 }}>
          Dataset: <code>{datasetId}</code>{" "}
          {phase !== "done" && "(processing…)"}
        </div>
      )}

      {log.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {log.map((l, i) => (
              <li key={i} style={{ fontSize: 14 }}>
                {l}
              </li>
            ))}
          </ul>
        </div>
      )}

      {err && (
        <div
          style={{
            marginTop: 10,
            color: "#a10000",
            background: "#fff1f1",
            padding: 8,
            borderRadius: 6,
          }}
        >
          {err}
        </div>
      )}

      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <button className="btn" onClick={reset} disabled={busy}>
          Reset
        </button>
        {phase === "done" && <span className="muted">Ready to search ✅</span>}
      </div>
    </div>
  )
}
