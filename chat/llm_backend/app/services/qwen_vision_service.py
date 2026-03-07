"""
通义千问多模态视觉解析服务
使用阿里云百炼 OpenAI 兼容接口调用 qwen3.5-flash / qwen3.5-plus 进行图片、视频、文件解析
"""

import asyncio
import os
from typing import Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(service="qwen_vision")

# 支持的多模态模型列表
QWEN_VISION_MODELS = ["qwen3.5-flash", "qwen3.5-plus"]
DEFAULT_QWEN_VISION_MODEL = "qwen3.5-flash"


class QwenVisionService:
    """通义千问多模态视觉解析服务"""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        """延迟初始化 OpenAI 客户端，确保配置更新后立即生效"""
        api_key = getattr(settings, "DASHSCOPE_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，无法调用通义千问多模态模型")
        # 每次都重新创建客户端以确保 API Key 更新后生效
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        return self._client

    def _get_mime_type(self, file_url: str) -> str:
        """根据 URL 或文件扩展名推断 MIME 类型"""
        ext = os.path.splitext(file_url.split("?")[0])[1].lower()
        mapping = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".silk": "audio/silk",
            ".amr": "audio/amr",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }
        return mapping.get(ext, "application/octet-stream")

    async def parse_by_url(
        self,
        file_url: str,
        prompt: str = "请详细分析并总结该文件的内容",
        model: str = DEFAULT_QWEN_VISION_MODEL,
        timeout: float = 60.0,
    ) -> Optional[str]:
        """
        使用通义千问多模态模型通过 URL 解析文件内容（图片、视频、文档等）。

        Args:
            file_url: 文件的公网可访问 URL（OSS 签名 URL 等）
            prompt: 解析提示词
            model: 模型名称，支持 qwen3.5-flash（默认）和 qwen3.5-plus
            timeout: 超时时间（秒）

        Returns:
            解析后的文本内容，失败返回 None
        """
        if model not in QWEN_VISION_MODELS:
            logger.warning(f"不支持的模型 {model}，回退到默认模型 {DEFAULT_QWEN_VISION_MODEL}")
            model = DEFAULT_QWEN_VISION_MODEL

        try:
            logger.info(f"使用 {model} 解析文件: {file_url[:80]}...")

            mime_type = self._get_mime_type(file_url)
            # 根据 MIME 类型构建不同的 content 部分
            content_parts = []

            if mime_type.startswith("image/"):
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": file_url},
                })
            elif mime_type.startswith("video/"):
                content_parts.append({
                    "type": "video_url",
                    "video_url": {"url": file_url},
                })
            elif mime_type.startswith("audio/"):
                content_parts.append({
                    "type": "input_audio",
                    "input_audio": {"data": file_url, "format": "url"},
                })
            else:
                # 文档类型（PDF/Word 等）使用 file_url
                content_parts.append({
                    "type": "file_url",
                    "file_url": {"url": file_url},
                })

            content_parts.append({"type": "text", "text": prompt})

            completion = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": content_parts,
                        }
                    ],
                ),
                timeout=timeout,
            )

            result_text = completion.choices[0].message.content
            if result_text:
                logger.info(f"{model} 解析成功，结果长度: {len(result_text)}")
                return result_text
            else:
                logger.error(f"{model} 返回空内容")
                return None

        except asyncio.TimeoutError:
            logger.error(f"{model} 解析超时（{timeout}s）: {file_url[:60]}")
            return None
        except asyncio.CancelledError:
            logger.warning(f"{model} 解析被取消: {file_url[:60]}")
            return None
        except Exception as e:
            logger.error(f"{model} 解析失败: {e!r}", exc_info=True)
            return None


# 全局单例
qwen_vision_service = QwenVisionService()
