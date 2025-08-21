import React from "react"

export default function Results({ data }) {
  if (!data) return null

  const items = Array.isArray(data.results) ? data.results : []
  const errored = data?.ok === false
  const header = errored
    ? "Search error"
    : `${items.length} result${items.length === 1 ? "" : "s"}`

  return (
    <div style={{ marginTop: 8 }}>
      <div className="section-title" aria-live="polite">
        {header}
      </div>

      {errored && (
        <pre className="error" role="alert">
          {String(data.error || "Unknown error")}
        </pre>
      )}

      <ul className="result-list">
        {items.map((r, i) => {
          const ts = r?.ts ? new Date(r.ts).toLocaleString() : ""
          const score =
            typeof r?.score === "number" ? r.score.toFixed(3) : r?.score ?? ""

          return (
            <li
              key={`${r.conv_id}-${r.msg}-${i}`}
              className="result-item surface"
            >
              <div className="result-meta">
                <span className="meta">{ts}</span>
                <span className="dot">•</span>
                <span className="meta">{r.role}</span>
                {score !== "" && (
                  <>
                    <span className="dot">•</span>
                    <span className="chip chip-score" title="Similarity score">
                      score&nbsp;{score}
                    </span>
                  </>
                )}
              </div>

              {r.title && <div className="result-title">{r.title}</div>}
              {r.snippet && <div className="result-snippet">{r.snippet}</div>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
