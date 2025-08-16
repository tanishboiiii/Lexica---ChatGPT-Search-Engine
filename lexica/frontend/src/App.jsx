import React, { useState } from "react"
import "./App.css"
import UploadBox from "./UploadBox"
import SearchBar from "./SearchBar"
import Results from "./Results"

export default function App() {
  const [datasetId, setDatasetId] = useState(null)
  const [results, setResults] = useState(null)

  return (
    <div className="container">
      <h1>Lexica</h1>
      <p className="muted">
        Upload your ChatGPT export (.zip or <code>conversations.json</code>).
        We’ll process it next.
      </p>

      {/* Make sure UploadBox calls onUploaded(datasetId) after a successful upload */}
      <UploadBox onUploaded={(ds) => setDatasetId(ds)} />

      {datasetId ? (
        <>
          <div className="muted" style={{ marginTop: 12 }}>
            Dataset: <code>{datasetId}</code>
          </div>

          <div style={{ marginTop: 16 }}>
            <SearchBar datasetId={datasetId} onResults={setResults} />
          </div>

          <Results data={results} />
        </>
      ) : (
        <div className="muted" style={{ marginTop: 16 }}>
          (Upload a dataset to enable search.)
        </div>
      )}
    </div>
  )
}
