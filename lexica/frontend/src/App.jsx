import React from "react"
import "./App.css"
import UploadBox from "./UploadBox"

export default function App() {
  return (
    <div className="container">
      <h1>Lexica</h1>
      <p className="muted">
        Upload your ChatGPT export (.zip or conversations.json). We’ll process
        it next.
      </p>
      <UploadBox />
    </div>
  )
}
