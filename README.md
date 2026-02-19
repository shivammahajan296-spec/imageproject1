# AI-Powered Intelligent Pack Design

Production-oriented FastAPI + vanilla JS app that enforces a strict packaging-engineering workflow from concept to approved 3D preview.

## Features
- Strict 7-step state-machine workflow (never jumps ahead).
- Backend-only integration with Straive LLM Foundry endpoints.
- Chat + image generation/edit + TripoSR 3D preview APIs.
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
- 3D conversion: TripoSR (approved 2D image -> 3D preview file)

## Environment Variables
Set these before running:

- `STRAIVE_API_KEY` (required for real Straive calls)
- `STRAIVE_MODEL` (optional, default `gpt-4o-mini`)
- `CORS_ORIGINS` (optional, comma-separated, default `*`)
- `APP_DB_PATH` (optional, default `app.db`)
- `ASSETS_DIR` (optional, default `assets`)
- `AUTO_INDEX_ASSETS` (optional, default `false`; if true, auto-indexes asset images during Step 3 baseline decision)
- `TRIPOSR_COMMAND` (required for 3D generation; example: `python run.py --input {input} --output-dir {output_dir}`)
- `TRIPOSR_OUTPUT_DIR` (optional, default `preview_3d`)
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

Open: [http://localhost:8000](http://localhost:8000)

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
- `POST /api/preview3d/generate`
  - Input: `{ session_id }`
  - Output: `{ message, preview_file }`
  - Action: generates 3D preview from the approved version image using TripoSR
- `GET /api/session/{session_id}`
  - Output: full session state
- `POST /api/brief/upload` (multipart form-data)
  - Input: `session_id`, `file` (PDF)
  - Output: `{ message, step, spec_summary, required_questions }`
  - Action: extracts design spec from marketing brief PDF without chat input
- `POST /api/session/clear`
  - Input: `{ session_id }`
  - Output: `{ message }`
  - Action: clears chat/spec/baseline/images/approvals/3D preview state for the session
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
6. Generate 3D preview via TripoSR from the approved version image.
7. View/open the generated 3D file.

## Example Session Walkthrough
1. User: "Need a cosmetic jar, 50 ml, PP, screw cap, matte premium look"
2. Assistant reaches Step 3 baseline decision.
   - If asset metadata is indexed and a close match exists, app uses that as baseline reference.
   - You can alternatively upload a marketing brief PDF to auto-fill spec fields before chat.
3. User clicks `Generate 2D Concept`.
4. User iterates: "cap taller, matte texture" and clicks `Run Edit`.
5. User approves a specific version in Version History.
6. User goes to Approve & 3D and clicks `Generate 3D Preview (TripoSR)`.
7. User opens the generated preview file (and GLB renders inline in 3D viewer when available).

## Notes
- Frontend never calls Straive directly.
- All Straive requests are server-side.
- If `STRAIVE_API_KEY` is missing, image endpoints return a safe placeholder preview for local testing.
- Approve & 3D screen is TripoSR-based (approve a version, then generate 3D preview).
