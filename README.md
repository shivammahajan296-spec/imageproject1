# AI-Powered Intelligent Pack Design

Production-oriented FastAPI + vanilla JS app that enforces a strict packaging-engineering workflow from concept to approved STEP CAD.

## Features
- Strict 7-step state-machine workflow (never jumps ahead).
- Backend-only integration with Straive LLM Foundry endpoints.
- Chat + image generation/edit APIs.
- LLM-generated CadQuery script + STEP export with server-side cache and in-app STEP viewer.
- Asset baseline search from local `assets/` images using AI-generated metadata.
- Session persistence in SQLite.
- Request validation, rate limiting, redacted logging, CORS.
- ChatGPT-style UI with design preview, version history, workflow indicator.
- 3-screen production flow:
  - Requirements + Baseline
  - Edit Studio (recommended edits + manual edits)
  - Approval + 3D status + viewer

## Tech
- Backend: FastAPI
- Frontend: HTML/CSS/JS
- AI Gateway: Straive LLM Foundry
- CAD kernel scripting: CadQuery (LLM-generated script executed server-side to export STEP)

## Environment Variables
Set these before running:

- `STRAIVE_API_KEY` (required for real Straive calls)
- `STRAIVE_MODEL` (optional, default `gpt-4o-mini`)
- `CORS_ORIGINS` (optional, comma-separated, default `*`)
- `APP_DB_PATH` (optional, default `app.db`)
- `ASSETS_DIR` (optional, default `assets`)
- `AUTO_INDEX_ASSETS` (optional, default `false`; if true, auto-indexes asset images during Step 3 baseline decision)
- `CACHE_DIR` (optional, default `/tmp/pack_design_cache`)
- `SESSION_IMAGES_DIR` (optional, default `/tmp/pack_design_session_images`)
- `LOG_LEVEL` (optional, default `INFO`)

## Per-User API Key Option
- UI includes a top-bar API key field for end users.
- The browser stores this key in local storage and sends it as `X-Straive-Api-Key`.
- Backend uses this per-request key in preference to server `STRAIVE_API_KEY`.
- If user key is empty, backend falls back to `STRAIVE_API_KEY`.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
1
Open: [http://localhost:8000](http://localhost:8000)

Note:
- Runtime-generated files are written under `/tmp` by default to avoid uvicorn `--reload` restarts interrupting in-flight CAD requests.
- If you intentionally keep runtime files inside the repo, run with excludes, for example:
```bash
uvicorn main:app --reload --reload-exclude 'tmp_runtime/*' --reload-exclude 'tmp_runtime/**'
```

Put reusable reference images in:
- `assets/` (or the folder configured by `ASSETS_DIR`)

## API Endpoints
- `POST /api/chat`
  - Input: `{ session_id, user_message }`
  - Output: `{ assistant_message, step, spec_summary, required_questions, can_generate_image, can_iterate_image, can_lock, can_generate_cad }`
- `POST /api/image/generate`
  - Input: `{ session_id, prompt }`
  - Output: `{ image_id, image_url_or_base64, version }`
- `POST /api/image/edit`
  - Input: `{ session_id, image_id, instruction_prompt }`
  - Output: `{ image_id, image_url_or_base64, version }`
- `POST /api/version/approve`
  - Input: `{ session_id, version }`
  - Output: `{ message, approved_version }`
  - Action: marks a version from history as approved source for 3D conversion
- `POST /api/cad/model/generate`
  - Input: `{ session_id, prompt }`
  - Output: `{ message, cad_code, code_file, step_file, cached }`
  - Action: sends prompt to Straive chat, generates CadQuery script, executes export to `.step`, caches by approved-image hash + prompt, and returns downloadable files.
- `POST /api/cache/clear`
  - Input: `{}`
  - Output: `{ message, removed_files }`
  - Action: clears image/CAD cache entries.
- `GET /api/session/{session_id}`
  - Output: full session state
- `POST /api/brief/upload` (multipart form-data)
  - Input: `session_id`, `file` (PDF)
  - Output: `{ message, step, spec_summary, required_questions }`
  - Action: extracts design spec from marketing brief PDF without chat input
- `POST /api/session/clear`
  - Input: `{ session_id }`
  - Output: `{ message }`
  - Action: clears chat/spec/baseline/images/approvals/CAD state for the session
- `GET /api/recommendations/{session_id}`
  - Output: `{ count, recommendations }`
  - Action: returns suggested visual refinements for Edit Studio
- `POST /api/assets/index`
  - Input: `{ force_reindex }`
  - Output: `{ indexed_count, total_assets }`
  - Action: runs AI metadata extraction for images in `assets/`, then baseline search at Step 3 uses these records
- `GET /api/assets/catalog`
  - Output: `{ total, items[] }`
  - Action: returns indexed asset metadata for the dedicated Assets DB screen

## Workflow Enforcement
1. Collect mandatory fields (product type, size/volume, material, closure, style).
2. Normalize spec internally.
3. Baseline decision statement.
4. 2D visual iteration only.
5. Approve one version from Edit Studio.
6. Generate STEP CAD from the approved version image.
7. View/open the generated STEP file and download CAD code.

## Example Session Walkthrough
1. User: "Need a cosmetic jar, 50 ml, PP, screw cap, matte premium look"
2. Assistant reaches Step 3 baseline decision.
   - If asset metadata is indexed and a close match exists, app uses that as baseline reference.
   - You can alternatively upload a marketing brief PDF to auto-fill spec fields before chat.
3. User clicks `Generate 2D Concept`.
4. User iterates: "cap taller, matte texture" and clicks `Run Edit`.
5. User approves a specific version in Version History.
6. User goes to Approve & 3D and clicks `Generate STEP CAD`.
7. User downloads CAD Python code and STEP file, and views STEP in the in-app viewer.

## Notes
- Frontend never calls Straive directly.
- All Straive requests are server-side.
- If `STRAIVE_API_KEY` is missing, image endpoints return a safe placeholder preview for local testing.
- Approve & 3D uses LLM-generated STEP CAD (with Three.js + OCCT viewer).
