import React, { useState } from "react"
import "./index.css"
import "./App.css"
import UploadBox from "./UploadBox"
import SearchBar from "./SearchBar"
import Results from "./Results"

export default function App() {
  const [datasetId, setDatasetId] = useState(null)
  const [results, setResults] = useState(null)

  return (
    <div className="app-root">
      <header className="app-header surface">
        <div className="brand">
          <img src="/lexica-logo.png" alt="Lexica logo" className="logo" />
          <span className="wordmark">Lexica</span>
        </div>
        <nav className="header-actions">
          <a
            className="link subtle"
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
        </nav>
      </header>

      <main className="container">
        <section className="hero">
          <h1 className="title">Your ChatGPT archive, searchable.</h1>
          <p className="subtitle">
            Upload your ChatGPT export (<code>.zip</code> or{" "}
            <code>conversations.json</code>). We’ll process it and make it
            instantly searchable.
          </p>
        </section>

        <section className="surface card-lg">
          <h2 className="section-title">Dataset</h2>
          <UploadBox onUploaded={(ds) => setDatasetId(ds)} />
          {datasetId ? (
            <div className="chip-row">
              <span className="chip chip-ok">Dataset ready</span>
              <span className="chip chip-id" title={datasetId}>
                {datasetId}
              </span>
            </div>
          ) : (
            <div className="empty-hint">Upload a dataset to enable search.</div>
          )}
        </section>

        <section className="surface card-lg">
          <h2 className="section-title">Search</h2>
          <div className="search-panel">
            <SearchBar datasetId={datasetId} onResults={setResults} />
          </div>
          <Results data={results} />
        </section>
      </main>

      <footer className="app-footer">
        <div className="container footer-inner">
          <span className="muted">© {new Date().getFullYear()} Lexica</span>
          <div className="footer-right">
            <a className="link subtle" href="#" aria-disabled>
              Privacy
            </a>
            <span className="dot">•</span>
            <a className="link subtle" href="#" aria-disabled>
              Terms
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
