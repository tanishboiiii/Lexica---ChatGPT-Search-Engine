import React from "react"

export default function Results({ data }) {
  if (!data) return null

  const items = Array.isArray(data.results) ? data.results : []
  const header = data.ok === false ? "Search error" : `${items.length} results`

  return (
    <div style={{ marginTop: 16 }}>
      <div className="muted" style={{ marginBottom: 8 }}>
        {header}
      </div>

      {data.ok === false && (
        <pre className="error">{String(data.error || "Unknown error")}</pre>
      )}

      <ul className="result-list">
        {items.map((r, i) => (
          <li key={`${r.conv_id}-${r.msg}-${i}`} className="result-item">
            <div className="result-meta">
              <span>{new Date(r.ts).toLocaleString()}</span>
              <span> · </span>
              <span>{r.role}</span>
              <span> · </span>
              <span>
                score:{" "}
                {typeof r.score === "number" ? r.score.toFixed(3) : r.score}
              </span>
            </div>
            <div className="result-title">{r.title}</div>
            {r.snippet && <div className="result-snippet">{r.snippet}</div>}
          </li>
        ))}
      </ul>
    </div>
  )
}
