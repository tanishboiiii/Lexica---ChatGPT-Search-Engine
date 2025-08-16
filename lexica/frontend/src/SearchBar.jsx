import React, { useState } from "react"

export default function SearchBar({ datasetId, onResults }) {
  const [q, setQ] = useState("")
  const [k, setK] = useState(10)
  const [role, setRole] = useState("")
  const [hasCode, setHasCode] = useState("")
  const [loading, setLoading] = useState(false)
  const disabled = !datasetId || !q || loading

  async function onSubmit(e) {
    e.preventDefault()
    if (!datasetId) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ q, k: String(k) })
      if (role) params.set("role", role)
      if (hasCode) params.set("has_code", hasCode) // backend expects has_code
      const url = `http://localhost:8000/datasets/${datasetId}/search?${params.toString()}`
      const res = await fetch(url)
      const data = await res.json()
      onResults?.(data)
    } catch (err) {
      console.error(err)
      onResults?.({ ok: false, error: String(err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="searchbar">
      <div className="row">
        <input
          className="input"
          placeholder="Search your ChatGPT history…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn" disabled={disabled}>
          {loading ? "Searching…" : "Search"}
        </button>
      </div>

      <div className="filters">
        <label>
          Top K:
          <input
            type="number"
            min={1}
            max={100}
            value={k}
            onChange={(e) => setK(Number(e.target.value))}
          />
        </label>

        <label>
          Role:
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">any</option>
            <option value="user">user</option>
            <option value="assistant">assistant</option>
          </select>
        </label>

        <label>
          Has code:
          <select value={hasCode} onChange={(e) => setHasCode(e.target.value)}>
            <option value="">either</option>
            <option value="true">yes</option>
            <option value="false">no</option>
          </select>
        </label>
      </div>
    </form>
  )
}
