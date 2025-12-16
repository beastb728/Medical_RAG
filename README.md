# perfect-rag (mxbai -> Chroma -> mistral)

## requirements
- ollama installed and running locally (default: http://127.0.0.1:11434)
- Python 3.10+

## pull models (run locally in terminal)
ollama pull mxbai-embed-large
ollama pull mistral

## install deps
pip install -r requirements.txt

## run
streamlit run app.py

Notes:
- If your ollama runs on a different host/port, set OLLAMA_HOST env var (ex: export OLLAMA_HOST="http://127.0.0.1:11434")
- If your ollama doesn't provide the HTTP embed/generate endpoints, edit the helper functions in embedder.py and rag_core.py to use the ollama CLI instead.
