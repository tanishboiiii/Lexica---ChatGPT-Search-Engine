# Lexica---ChatGPT-Search-Engine
Creating a search engine for users chatgpt chat history rather than relying on OpenAI's chat search that only uses textbased matching rather than context matching.

**Running Lexica:**
- Open a new terminal
- cd .\Lexica---ChatGPT-Search-Engine\
- cd lexica
- cd frontend
- npm install
- npm run dev
- Open a new seperate terminal
- cd .\Lexica---ChatGPT-Search-Engine\
- cd lexica
- cd backend
- .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
