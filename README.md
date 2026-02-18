# AI-Powered Intelligent Pack Design

Production-oriented FastAPI + vanilla JS app that enforces a strict packaging-engineering workflow from concept to CAD code.

## Features
- Strict 7-step state-machine workflow (never jumps ahead).
- Backend-only integration with Straive LLM Foundry endpoints.
- Chat + image generation/edit + CAD code generation APIs.
- Asset baseline search from local `assets/` images using AI-generated metadata.
- Session persistence in SQLite.
- Request validation, rate limiting, redacted logging, CORS.
- ChatGPT-style UI with design preview, version history, workflow indicator.
- 3-screen production flow:
  - Requirements + Baseline
  - Edit Studio (recommended edits + manual edits)
  - Approval + 3D status + CAD download

## Tech
- Backend: FastAPI
- Frontend: HTML/CSS/JS
- AI Gateway: Straive LLM Foundry
- CAD: CadQuery code generation (Python code output only)

## Environment Variables
Set these before running:

- `STRAIVE_API_KEY` (required for real Straive calls)
- `STRAIVE_MODEL` (optional, default `gpt-4o-mini`)
- `CORS_ORIGINS` (optional, comma-separated, default `*`)
- `APP_DB_PATH` (optional, default `app.db`)
- `ASSETS_DIR` (optional, default `assets`)
- `AUTO_INDEX_ASSETS` (optional, default `true`; auto-indexes only new asset images during Step 3 baseline decision)
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
- `POST /api/cad/generate`
  - Input: `{ session_id }`
  - Output: `{ cadquery_code, design_summary }`
- `GET /api/session/{session_id}`
  - Output: full session state
- `GET /api/recommendations/{session_id}`
  - Output: `{ count, recommendations }`
  - Action: returns suggested visual refinements for Edit Studio
- `POST /api/assets/index`
  - Input: `{ force_reindex }`
  - Output: `{ indexed_count, total_assets }`
  - Action: runs AI metadata extraction for images in `assets/`, then baseline search at Step 3 uses these records

## Workflow Enforcement
1. Collect mandatory fields (product type, size/volume, material, closure, style).
2. Normalize spec internally.
3. Baseline decision statement.
4. 2D visual iteration only.
5. Mandatory lock question: `Do you want to lock this design and generate the 3D CAD (STEP) file?`
6. Generate CadQuery code after lock confirmation only.
7. Return summary + code + STEP export confirmation.

## CAD Support
Implemented parametric generators:
1. Cosmetic Jar + Screw Cap
2. Bottle + Flip-Top Cap (simplified)

CAD generation is blocked unless required dimensions are present.

## Example Session Walkthrough
1. User: "Need a cosmetic jar, 50 ml, PP, screw cap, matte premium look"
2. Assistant reaches Step 3 baseline decision.
   - If asset metadata is indexed and a close match exists, app uses that as baseline reference.
3. User clicks `Generate 2D Concept`.
4. User iterates: "cap taller, matte texture" and clicks `Iterate Design`.
5. User says final/ready; assistant asks lock question.
6. User confirms lock.
7. App auto-triggers CAD generation; returns summary + CadQuery code and enables download.

## Notes
- Frontend never calls Straive directly.
- All Straive requests are server-side.
- If `STRAIVE_API_KEY` is missing, image endpoints return a safe placeholder preview for local testing.
