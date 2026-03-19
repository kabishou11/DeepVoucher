from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import time
from typing import Any

import httpx
from openai import APIConnectionError, BadRequestError, OpenAI
from PIL import Image

from core.config.settings import get_settings


class ModelScopeClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.openai_client = OpenAI(
            base_url=self.settings.modelscope_base_url,
            api_key=self.settings.modelscope_api_key,
            timeout=float(self.settings.llm_timeout_seconds),
        )

    async def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.modelscope_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.modelscope_chat_model,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.settings.modelscope_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def chat_completion(self, messages: list[dict[str, Any]]) -> str:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.settings.modelscope_chat_model,
                    messages=messages,
                    stream=False,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and _is_retryable_modelscope_error(exc):
                    time.sleep(1 + attempt)
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("ModelScope chat completion failed without an explicit exception.")

    def image_message(self, prompt: str, image_path: str | Path) -> list[dict[str, Any]]:
        return self.multi_image_message(prompt, [image_path])

    def multi_image_message(self, prompt: str, image_paths: list[str | Path]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            mime_type, payload = encode_image_for_modelscope(image_path)
            encoded = base64.b64encode(payload).decode("ascii")
            data_url = f"data:{mime_type};base64,{encoded}"
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        return [{"role": "user", "content": content}]


def extract_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return json.loads(cleaned[start : end + 1])


def encode_image_for_modelscope(image_path: str | Path, max_side: int = 2048) -> tuple[str, bytes]:
    path = Path(image_path)
    with Image.open(path) as img:
        if img.mode not in {"RGB", "L"}:
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side))

        buffer = io.BytesIO()
        save_format = "PNG" if path.suffix.lower() == ".png" else "JPEG"
        mime_type = "image/png" if save_format == "PNG" else "image/jpeg"
        save_kwargs = {"optimize": True}
        if save_format == "JPEG":
            save_kwargs["quality"] = 90
        img.save(buffer, format=save_format, **save_kwargs)
        return mime_type, buffer.getvalue()


def _is_retryable_modelscope_error(exc: Exception) -> bool:
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, BadRequestError) and "inappropriate content" in str(exc).lower():
        return True
    if isinstance(exc, httpx.HTTPError):
        return True
    return False
