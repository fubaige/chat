import asyncio
import base64
import httpx
import os
from pathlib import Path
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(service="gemini")

class GeminiService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY

    @property
    def base_url(self) -> str:
        # 动态拼接，确保配置更新后立即生效
        return settings.GEMINI_PARSE_URL
        
    def _get_mime_type(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        mapping = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".txt": "text/plain"
        }
        mime_type = mapping.get(ext)
        if mime_type:
            return mime_type
        import mimetypes
        guess, _ = mimetypes.guess_type(file_path)
        return guess or "application/octet-stream"

    def _encode_file_to_base64(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def parse_file(
        self,
        file_path: str,
        prompt: str = "请详细分析并总结该文件的内容",
        timeout: float = 60.0,
    ) -> Optional[str]:
        """
        使用 Gemini API 解析文件内容（图片或 PDF）。
        - 文件读取放到线程池，不阻塞事件循环
        - timeout 控制单次 HTTP 请求超时，默认 60s
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return None

            mime_type = self._get_mime_type(file_path)
            # 同步 IO 放线程池，避免阻塞事件循环
            base64_data = await asyncio.to_thread(self._encode_file_to_base64, file_path)

            logger.info(f"Using Gemini to parse {file_path} (Type: {mime_type})")

            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": base64_data}},
                            {"text": prompt},
                        ],
                    }
                ]
            }

            headers = {"Content-Type": "application/json"}
            # Gemini API 使用 ?key= 查询参数认证，与图片生成服务保持一致
            url = self.base_url
            url = f"{url}&key={self.api_key}" if "?" in url else f"{url}?key={self.api_key}"

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                result = response.json()
                try:
                    return result["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as e:
                    logger.error(f"Failed to extract text from Gemini response: {e}, Response: {result}")
                    return None
            else:
                logger.error(f"Gemini API request failed: {response.status_code} - {response.text}")
                return None

        except asyncio.TimeoutError:
            logger.error(f"Gemini parse_file timed out after {timeout}s for {file_path}")
            return None
        except asyncio.CancelledError:
            # Python 3.8+ CancelledError 继承自 BaseException，需单独捕获
            # 外部请求取消（如 Starlette 中间件）会传播 CancelledError，此处吞掉并返回 None
            logger.warning(f"Gemini parse_file was cancelled for {file_path}")
            return None
        except Exception as e:
            logger.error(f"Error in GeminiService.parse_file: {e!r}", exc_info=True)
            return None


gemini_service = GeminiService()
