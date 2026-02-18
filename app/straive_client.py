from __future__ import annotations

import base64
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

    async def image_generate(self, prompt: str, api_key_override: str | None = None) -> dict[str, str]:
        if not (api_key_override or self.settings.straive_api_key):
            return self._fallback_image(prompt)

        payload = {"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024"}
        logger.info("Straive image generate request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.settings.image_generate_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive image generate response: %s", self._redact(data))
            item = data.get("data", [{}])[0]
            return {
                "image_id": item.get("id", "generated-image"),
                "image_url_or_base64": item.get("url") or item.get("b64_json", ""),
            }

    async def image_edit(
        self, image_ref: str, instruction_prompt: str, api_key_override: str | None = None
    ) -> dict[str, str]:
        if not (api_key_override or self.settings.straive_api_key):
            return self._fallback_image(f"{image_ref}: {instruction_prompt}")

        payload = {
            "model": "gpt-image-1",
            "image": image_ref,
            "prompt": instruction_prompt,
            "size": "1024x1024",
        }
        logger.info("Straive image edit request: %s", self._redact(payload))
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.settings.image_edit_url,
                headers=self._headers(api_key_override=api_key_override),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Straive image edit response: %s", self._redact(data))
            item = data.get("data", [{}])[0]
            return {
                "image_id": item.get("id", "edited-image"),
                "image_url_or_base64": item.get("url") or item.get("b64_json", ""),
            }

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
            "Return only valid JSON with keys: product_type, material, closure_type, design_style, "
            "size_or_volume, tags (array of short strings), summary."
        )
        user_content = [
            {"type": "text", "text": "Extract packaging metadata for baseline matching. Keep values concise."},
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
                return raw
        except json.JSONDecodeError:
            pass
        return {}

    @staticmethod
    def _normalize_asset_metadata(data: dict[str, Any], image_path: Path) -> dict[str, Any]:
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return {
            "product_type": str(data.get("product_type", "")).lower() or None,
            "material": str(data.get("material", "")).lower() or None,
            "closure_type": str(data.get("closure_type", "")).lower() or None,
            "design_style": str(data.get("design_style", "")).lower() or None,
            "size_or_volume": str(data.get("size_or_volume", "")).lower() or None,
            "tags": [str(t).lower() for t in tags[:12] if str(t).strip()],
            "summary": str(data.get("summary", "")).strip() or f"Baseline metadata for {image_path.name}",
        }

    @staticmethod
    def _fallback_asset_metadata(image_path: Path) -> dict[str, Any]:
        stem = image_path.stem.lower().replace("-", " ").replace("_", " ")
        material = "glass" if "glass" in stem else ("pp" if "pp" in stem else None)
        product_type = "jar" if "jar" in stem else ("bottle" if "bottle" in stem else None)
        closure = "flip top" if "flip" in stem else ("screw" if "screw" in stem else None)
        style = "matte" if "matte" in stem else ("luxury" if "luxury" in stem else None)
        return {
            "product_type": product_type,
            "material": material,
            "closure_type": closure,
            "design_style": style,
            "size_or_volume": None,
            "tags": [w for w in stem.split() if w][:10],
            "summary": f"Filename-derived baseline metadata for {image_path.name}",
        }
