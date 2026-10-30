# BOOKORA — Full-stack translation starter

A Persian-language web interface and FastAPI backend for translating PDF books page-by-page. It extracts embedded PDF text, falls back to OCR for scanned pages, translates through Google Cloud Translation, creates a designed PNG for each translated page, and returns a ZIP. The frontend can preview the first six pages and downloads the complete ZIP.

## Requirements before real use
1. A Google Cloud project with Cloud Translation API enabled and billing configured.
2. A server-side API key with appropriate restrictions. Never put this key in browser JavaScript.
3. Set `BOOKORA_USERNAME` and `BOOKORA_PASSWORD` to strong, unique values in the hosting environment. Do not use the example values in production.
4. Docker, or Python 3.12 plus Tesseract OCR.

Translation usage can incur provider charges. Configure quotas/budgets and restrict the API key. Only translate books you own or are authorized to process.

## Run with Docker
```bash
cp .env.example .env
# Edit .env and set GOOGLE_TRANSLATE_API_KEY, BOOKORA_USERNAME and BOOKORA_PASSWORD.
# GOOGLE_TRANSLATE_API_KEY must be a valid Google Cloud API key with
# Cloud Translation API enabled and billing configured.
docker build -t bookora .
docker run --env-file .env -p 8000:8000 bookora
```
Open `http://localhost:8000`; the browser will request the private-site username and password. API docs are also protected at `http://localhost:8000/docs`. For a real deployment, use HTTPS; Basic Auth over plain HTTP is not safe on a public network.

## Run without Docker
Install system Tesseract OCR and its English language pack, then:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Export GOOGLE_TRANSLATE_API_KEY in your shell
uvicorn app.main:app --reload
```

## API
- `GET /health` — minimal service status (public; does not reveal secrets)
- `GET /api/languages` — target languages
- `POST /api/translate` — multipart `file` (PDF) and `target_language` (e.g. `fa`, `en`, `de`); returns a ZIP of page PNGs.

## Known limitations — read before production
- The generated pages use a clean BOOKORA layout. They do not preserve the original PDF's exact typography, columns, illustrations, or page design.
- OCR is configured for English by default. For other source languages, install the matching Tesseract language data and set `OCR_LANG`. Mixed-language OCR may require a combined language code.
- The current request runs synchronously. Large books can take time and may exceed hosting request timeouts. Production should use background jobs, persistent object storage, per-user authentication, rate limiting, usage quotas, malware scanning, and automatic file deletion.
- Browser preview uses JSZip from a CDN; ZIP download still works if that CDN is unavailable.
- For Persian/Arabic page rendering, the container includes Noto fonts and shaping libraries. If your chosen font differs, set `BOOKORA_FONT`.
- This project is a deployable codebase, not an already-hosted live website. A translation API key and deployment are still required.

## Private access
All routes other than `/health` (including the website, static assets, API and documentation) are protected with HTTP Basic Authentication. Configure `BOOKORA_USERNAME` and `BOOKORA_PASSWORD` as environment variables on the server. If either is missing, the app fails closed and returns HTTP 503 instead of exposing the site. Use a long, unique password and deploy behind HTTPS. Basic Auth is a simple private-access gate, not a substitute for a full user-account system.
