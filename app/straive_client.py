from __future__ import annotations

import base64
import ast
import imghdr
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class StraiveClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self, api_key_override: str | None = None) -> dict[str, str]:
        api_key = api_key_override or self.settings.straive_api_key
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, str) and len(value) > 200:
            return value[:120] + "...[redacted]"
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if "key" in k.lower() or "authorization" in k.lower():
                    out[k] = "[redacted]"
                else:
                    out[k] = StraiveClient._redact(v)
            return out
        if isinstance(value, list):
            return [StraiveClient._redact(i) for i in value]
        return value

    async def chat(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
        api_key_override: str | None = None,
    ) -> str | None:
        if not (api_key_override or self.settings.straive_api_key):
            return None

        messages = [{"role": "system", "content": system_prompt}] + history + [
            {"role": "user", "content": user_message}
        ]
        payload = {"model": self.settings.model_name, "messages": messages, "temperature": 0.2}
        logger.info("Straive chat request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                self.settings.chat_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive chat response: %s", self._redact(data))
            return data.get("choices", [{}])[0].get("message", {}).get("content")

    async def cad_codegen(
        self,
        provider: str,
        system_prompt: str,
        user_message: str,
        api_key_override: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
    ) -> str | None:
        if not (api_key_override or self.settings.straive_api_key):
            return None

        mode = (provider or "").strip().lower()
        if mode == "gpt":
            return await self._cad_codegen_gpt(
                system_prompt=system_prompt,
                user_message=user_message,
                api_key_override=api_key_override,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
        return await self._cad_codegen_gemini(
            system_prompt=system_prompt,
            user_message=user_message,
            api_key_override=api_key_override,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )

    async def _cad_codegen_gemini(
        self,
        system_prompt: str,
        user_message: str,
        api_key_override: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
    ) -> str | None:
        if not (api_key_override or self.settings.straive_api_key):
            return None

        merged_prompt = f"{system_prompt.strip()}\n\n{user_message.strip()}".strip()
        parts: list[dict[str, Any]] = [{"text": merged_prompt}]
        if image_bytes:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image_mime_type or "image/png",
                        "data": base64.b64encode(image_bytes).decode("utf-8"),
                    }
                }
            )

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
        }
        logger.info("Straive CAD codegen request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=90) as client:
            try:
                resp = await client.post(
                    self.settings.cad_codegen_url,
                    headers=self._headers(api_key_override=api_key_override),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info("Straive CAD codegen response: %s", self._redact(data))
                return self._extract_vertex_text(data)
            except httpx.HTTPStatusError as exc:
                body = (exc.response.text or "")[:500]
                raise RuntimeError(f"HTTP {exc.response.status_code} from Gemini provider: {body}") from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError("Gemini provider timeout.") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Gemini provider network error: {exc}") from exc

    async def _cad_codegen_gpt(
        self,
        system_prompt: str,
        user_message: str,
        api_key_override: str | None = None,
        image_bytes: bytes | None = None,
        image_mime_type: str | None = None,
    ) -> str | None:
        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        if image_bytes:
            mime = image_mime_type or "image/png"
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}})

        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content if len(user_content) > 1 else user_message},
            ],
            "temperature": 0.2,
        }
        logger.info("Straive CAD GPT request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=90) as client:
            try:
                resp = await client.post(
                    self.settings.chat_url,
                    headers=self._headers(api_key_override=api_key_override),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info("Straive CAD GPT response: %s", self._redact(data))
                return self._extract_openai_text(data)
            except httpx.HTTPStatusError as exc:
                body = (exc.response.text or "")[:500]
                raise RuntimeError(f"HTTP {exc.response.status_code} from GPT provider: {body}") from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError("GPT provider timeout.") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"GPT provider network error: {exc}") from exc

    async def image_generate(self, prompt: str, api_key_override: str | None = None) -> dict[str, str]:
        if not (api_key_override or self.settings.straive_api_key):
            return self._fallback_image(prompt)

        payload = {
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        data = await self._post_image_generate(payload, api_key_override=api_key_override)
        item = data.get("data", [{}])[0]
        img = item.get("b64_json") or item.get("url", "")
        if img.startswith("http"):
            img = await self._url_to_b64(img, api_key_override=api_key_override)
        return {
            "image_id": item.get("id", "generated-image"),
            "image_url_or_base64": img,
        }

    async def image_edit(
        self, image_ref: str, instruction_prompt: str, api_key_override: str | None = None
    ) -> dict[str, str]:
        if not (api_key_override or self.settings.straive_api_key):
            return self._fallback_image(f"{image_ref}: {instruction_prompt}")

        image_bytes, mime_type, filename = await self._image_ref_to_bytes(image_ref)
        result = await self._post_image_edit_with_fallbacks(
            instruction_prompt=instruction_prompt,
            image_ref=image_ref,
            image_bytes=image_bytes,
            mime_type=mime_type,
            filename=filename,
            api_key_override=api_key_override,
        )
        item = result.get("data", [{}])[0]
        img = item.get("b64_json") or item.get("url", "")
        if img.startswith("http"):
            img = await self._url_to_b64(img, api_key_override=api_key_override)
        return {
            "image_id": item.get("id", "edited-image"),
            "image_url_or_base64": img,
        }

    async def _image_ref_to_bytes(self, image_ref: str) -> tuple[bytes, str, str]:
        raw = (image_ref or "").strip()
        if not raw:
            raise ValueError("Empty image reference provided for edit.")

        p = Path(raw)
        if p.exists() and p.is_file():
            blob = p.read_bytes()
            hinted = mimetypes.guess_type(str(p))[0]
            mime_type = self._detect_image_mime(blob, hinted_mime=hinted)
            ext = mimetypes.guess_extension(mime_type) or ".png"
            return blob, mime_type, f"edit_input{ext}"

        if raw.startswith("data:image"):
            header, b64_data = raw.split(",", 1)
            mime_match = re.search(r"data:(image/[^;]+);base64", header)
            hinted_mime = mime_match.group(1) if mime_match else None
            blob = base64.b64decode(b64_data)
            mime_type = self._detect_image_mime(blob, hinted_mime=hinted_mime)
            ext = mimetypes.guess_extension(mime_type) or ".png"
            return blob, mime_type, f"edit_input{ext}"

        if raw.startswith("http://") or raw.startswith("https://"):
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.get(raw)
                resp.raise_for_status()
                mime_type = resp.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
                ext = mimetypes.guess_extension(mime_type) or ".png"
                return resp.content, mime_type, f"edit_input{ext}"

        # Assume bare base64 image payload
        blob = base64.b64decode(raw)
        mime_type = self._detect_image_mime(blob, hinted_mime=None)
        ext = mimetypes.guess_extension(mime_type) or ".png"
        return blob, mime_type, f"edit_input{ext}"

    async def _url_to_b64(self, url: str, api_key_override: str | None = None) -> str:
        headers = {}
        token = api_key_override or self.settings.straive_api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")

    @staticmethod
    def _detect_image_mime(blob: bytes, hinted_mime: str | None = None) -> str:
        kind = imghdr.what(None, h=blob)
        mapping = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
            "bmp": "image/bmp",
        }
        detected = mapping.get((kind or "").lower())
        if detected:
            return detected
        if hinted_mime and hinted_mime.startswith("image/"):
            return hinted_mime
        return "image/png"

    async def _post_image_generate(
        self, payload: dict[str, Any], api_key_override: str | None = None
    ) -> dict[str, Any]:
        logger.info("Straive image generate request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.settings.image_generate_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            if resp.status_code >= 400 and "response_format" in payload:
                # Compatibility fallback for gateways that do not support response_format in images API.
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                logger.warning("Image generate retrying without response_format due to status %s", resp.status_code)
                resp = await client.post(
                    self.settings.image_generate_url,
                    headers=self._headers(api_key_override=api_key_override),
                    json=fallback_payload,
                )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive image generate response: %s", self._redact(data))
            return data

    async def _post_image_edit(
        self,
        url: str,
        data: dict[str, Any],
        image_bytes: bytes,
        mime_type: str,
        filename: str,
        api_key_override: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Straive image edit request: %s", self._redact(data))
        auth_headers = {"Authorization": f"Bearer {api_key_override or self.settings.straive_api_key}"}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                url,
                headers=auth_headers,
                data=data,
                files={"image": (filename, image_bytes, mime_type)},
            )
            resp.raise_for_status()
            out = resp.json()
            logger.info("Straive image edit response: %s", self._redact(out))
            return out

    async def _post_image_edit_json(
        self, url: str, payload: dict[str, Any], api_key_override: str | None = None
    ) -> dict[str, Any]:
        logger.info("Straive image edit JSON request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            out = resp.json()
            logger.info("Straive image edit JSON response: %s", self._redact(out))
            return out

    async def _post_image_edit_with_fallbacks(
        self,
        instruction_prompt: str,
        image_ref: str,
        image_bytes: bytes,
        mime_type: str,
        filename: str,
        api_key_override: str | None = None,
    ) -> dict[str, Any]:
        urls = [self.settings.image_edit_url]
        if "/openai/" in self.settings.image_edit_url:
            urls.append(self.settings.image_edit_url.replace("/openai/", "/"))

        errors: list[str] = []
        # 1) Multipart style exactly like known working snippet.
        for url in urls:
            try:
                return await self._post_image_edit(
                    url=url,
                    data={"model": "gpt-image-1", "prompt": instruction_prompt},
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    filename=filename,
                    api_key_override=api_key_override,
                )
            except Exception as exc:
                errors.append(f"multipart-basic@{url}: {exc}")

        # 2) Multipart + response_format hint.
        for url in urls:
            try:
                return await self._post_image_edit(
                    url=url,
                    data={"model": "gpt-image-1", "prompt": instruction_prompt, "response_format": "b64_json"},
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    filename=filename,
                    api_key_override=api_key_override,
                )
            except Exception as exc:
                errors.append(f"multipart-b64@{url}: {exc}")

        # 3) JSON fallback (some gateways only support json image input in this path).
        data_url_ref = image_ref if image_ref.startswith("data:image") else f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        for url in urls:
            try:
                return await self._post_image_edit_json(
                    url=url,
                    payload={"model": "gpt-image-1", "image": data_url_ref, "prompt": instruction_prompt},
                    api_key_override=api_key_override,
                )
            except Exception as exc:
                errors.append(f"json@{url}: {exc}")

        raise RuntimeError("All edit strategies failed: " + " | ".join(errors[:3]))

    async def describe_packaging_asset(
        self, image_path: Path, api_key_override: str | None = None
    ) -> dict[str, Any]:
        if not (api_key_override or self.settings.straive_api_key):
            return self._fallback_asset_metadata(image_path)

        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        data_url = f"data:{mime_type};base64,{image_b64}"

        system_prompt = (
            "You are a packaging image metadata extractor. "
            "Return strict JSON only with exactly these keys and no extras: "
            "product_type, material, closure_type, design_style, size_or_volume. "
            "If a value is unknown, return null."
        )
        user_content = [
            {"type": "text", "text": "Extract only the required fields for baseline matching."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        logger.info("Straive asset metadata request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                self.settings.chat_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive asset metadata response: %s", self._redact(data))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            parsed = self._parse_json_object(content)
            return self._normalize_asset_metadata(parsed, image_path)

    async def extract_design_spec_from_brief(
        self, brief_text: str, api_key_override: str | None = None
    ) -> dict[str, Any]:
        if not (api_key_override or self.settings.straive_api_key):
            return {}

        trimmed = brief_text[:24000]
        system_prompt = (
            "Extract packaging design requirements from a marketing brief. "
            "Return strict JSON only with keys: "
            "product_type, size_or_volume, intended_material, closure_type, design_style, dimensions. "
            "Use null for unknowns. dimensions must be an object of numeric mm values if present."
        )
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": trimmed},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        logger.info("Straive brief extraction request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.settings.chat_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive brief extraction response: %s", self._redact(data))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return self._parse_json_object(content)

    def _fallback_image(self, label: str) -> dict[str, str]:
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='1024' height='1024'>
<rect width='100%' height='100%' fill='white'/>
<rect x='120' y='100' width='784' height='824' rx='24' fill='#f7f7f7' stroke='#F57C00' stroke-width='8'/>
<text x='512' y='460' text-anchor='middle' fill='#444' font-size='40' font-family='Arial'>Preview Placeholder</text>
<text x='512' y='520' text-anchor='middle' fill='#666' font-size='26' font-family='Arial'>{label[:60]}</text>
</svg>"""
        b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
        return {"image_id": "fallback-image", "image_url_or_base64": f"data:image/svg+xml;base64,{b64}"}

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        try:
            raw = json.loads(stripped)
            if isinstance(raw, dict):
                if isinstance(raw.get("metadata"), dict):
                    return raw["metadata"]
                return raw
        except json.JSONDecodeError:
            pass
        # Try extracting the first JSON-like object from free-form model output.
        match = re.search(r"\{[\s\S]*\}", stripped)
        if match:
            candidate = match.group(0)
            try:
                raw = json.loads(candidate)
                if isinstance(raw, dict):
                    if isinstance(raw.get("metadata"), dict):
                        return raw["metadata"]
                    return raw
            except json.JSONDecodeError:
                try:
                    py_obj = ast.literal_eval(candidate)
                    if isinstance(py_obj, dict):
                        if isinstance(py_obj.get("metadata"), dict):
                            return py_obj["metadata"]
                        return py_obj
                except Exception:
                    pass
        return {}

    @staticmethod
    def _extract_vertex_text(data: dict[str, Any]) -> str | None:
        try:
            candidates = data.get("candidates", [])
            if not isinstance(candidates, list) or not candidates:
                return None
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not isinstance(parts, list):
                return None
            chunks: list[str] = []
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
            text = "\n".join(chunks).strip()
            return text or None
        except Exception:
            return None

    @staticmethod
    def _extract_openai_text(data: dict[str, Any]) -> str | None:
        try:
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip() or None
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        parts.append(part["text"])
                text = "\n".join(parts).strip()
                return text or None
        except Exception:
            return None
        return None

    @staticmethod
    def _normalize_asset_metadata(data: dict[str, Any], image_path: Path) -> dict[str, Any]:
        def _clean_scalar(value: Any) -> str | None:
            if value is None:
                return None
            txt = str(value).strip().lower()
            if not txt or txt in {"none", "null", "n/a", "na", "unknown"}:
                return None
            return txt

        normalized = {
            "product_type": _clean_scalar(data.get("product_type")),
            "material": _clean_scalar(data.get("material")),
            "closure_type": _clean_scalar(data.get("closure_type")),
            "design_style": _clean_scalar(data.get("design_style")),
            "size_or_volume": _clean_scalar(data.get("size_or_volume")),
        }
        if any(normalized.values()):
            return normalized
        return StraiveClient._fallback_asset_metadata(image_path)

    @staticmethod
    def _fallback_asset_metadata(image_path: Path) -> dict[str, Any]:
        stem = image_path.stem.lower().replace("-", " ").replace("_", " ")
        material = None
        for m in ["glass", "pp", "pet", "hdpe", "aluminum", "paper"]:
            if m in stem:
                material = m
                break
        product_type = None
        for p in ["jar", "bottle", "container", "cap"]:
            if p in stem:
                product_type = p
                break
        closure = None
        if "flip" in stem:
            closure = "flip top"
        elif "screw" in stem or "thread" in stem:
            closure = "screw"
        elif "pump" in stem:
            closure = "pump"
        elif "snap" in stem:
            closure = "snap"

        style = None
        for s in ["matte", "glossy", "minimal", "luxury", "premium", "clinical", "playful"]:
            if s in stem:
                style = s
                break

        size_or_volume = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l|cc|oz|mm|cm)\b", stem)
        if m:
            size_or_volume = f"{m.group(1)} {m.group(2)}"
        return {
            "product_type": product_type,
            "material": material,
            "closure_type": closure,
            "design_style": style,
            "size_or_volume": size_or_volume,
        }
