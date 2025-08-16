import React, { useRef, useState, useEffect } from "react"

const API_BASE = "http://localhost:8000"

export default function UploadBox() {
  const inputRef = useRef(null)
  const dzRef = useRef(null)
  const [progress, setProgress] = useState(0)
  const [datasetId, setDatasetId] = useState("")
  const [error, setError] = useState("")
  const [savedPath, setSavedPath] = useState("")

  useEffect(() => {
    if (!dzRef.current) return
    const dz = dzRef.current
    const onEnter = (e) => {
      e.preventDefault()
      dz.classList.add("hover")
    }
    const onOver = (e) => {
      e.preventDefault()
    }
    const onLeave = (e) => {
      e.preventDefault()
      dz.classList.remove("hover")
    }
    const onDrop = (e) => {
      e.preventDefault()
      dz.classList.remove("hover")
      if (e.dataTransfer.files?.[0])
        inputRef.current.files = e.dataTransfer.files
    }
    dz.addEventListener("dragenter", onEnter)
    dz.addEventListener("dragover", onOver)
    dz.addEventListener("dragleave", onLeave)
    dz.addEventListener("drop", onDrop)
    return () => {
      dz.removeEventListener("dragenter", onEnter)
      dz.removeEventListener("dragover", onOver)
      dz.removeEventListener("dragleave", onLeave)
      dz.removeEventListener("drop", onDrop)
    }
  }, [])

  const onSubmit = (e) => {
    e.preventDefault()
    setError("")
    setDatasetId("")
    setSavedPath("")
    setProgress(0)

    const file = inputRef.current?.files?.[0]
    if (!file) {
      setError("Choose a .zip or conversations.json file.")
      return
    }
    const name = (file.name || "").toLowerCase()
    if (!(name.endsWith(".zip") || name.endsWith(".json"))) {
      setError("Upload a ChatGPT export .zip or conversations.json")
      return
    }

    const fd = new FormData()
    fd.append("file", file)

    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API_BASE}/upload`, true)

    // progress of the upload (client → server)
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        setProgress(Math.round((ev.loaded / ev.total) * 100))
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText)
          setDatasetId(data.dataset_id)
          setSavedPath(data.path || "")
        } catch {
          setError("Unexpected server response.")
        }
      } else {
        setError(xhr.responseText || "Upload failed.")
      }
    }

    xhr.onerror = () => setError("Network error during upload.")
    xhr.send(fd)
  }

  return (
    <div className="card">
      <form onSubmit={onSubmit}>
        <div ref={dzRef} className="dropzone">
          <input ref={inputRef} type="file" accept=".zip,.json" />
          <p>
            Drop your <strong>.zip</strong> or <code>conversations.json</code>{" "}
            here, or click to choose.
          </p>
        </div>
        <div className="actions">
          <button type="submit">Upload</button>
        </div>

        {progress > 0 && (
          <div className="progress" aria-label="upload progress">
            <div className="bar" style={{ width: `${progress}%` }} />
            <span className="label">{progress}%</span>
          </div>
        )}

        {datasetId && (
          <div className="success">
            Upload complete.
            <br />
            Dataset ID: <strong>{datasetId}</strong>
            <br />
            {savedPath && <span className="muted">Saved to: {savedPath}</span>}
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </form>
    </div>
  )
}
