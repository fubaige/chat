"""
Gemini 图片生成服务
支持：纯文字生成图片 / 参考图+提示词生成图片
生成的 base64 图片自动保存为文件，返回可访问的 URL
"""
import base64
import httpx
import json
import uuid
from pathlib import Path
from typing import Optional, Tuple
from app.core.logger import get_logger

logger = get_logger(service="gemini_image_gen")

# 图片保存目录（相对于 llm_backend 运行目录）
GENERATED_IMAGE_DIR = Path("static/generated_images")


def _save_base64_image(b64_data: str, mime: str) -> str:
    """
    将 base64 图片数据保存为文件，返回相对 URL 路径
    例如：/static/generated_images/abc123.png
    """
    GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }
    ext = ext_map.get(mime, "png")
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = GENERATED_IMAGE_DIR / filename

    img_bytes = base64.b64decode(b64_data)
    file_path.write_bytes(img_bytes)
    logger.info(f"生成图片已保存: {file_path}")

    return f"/static/generated_images/{filename}"


async def generate_image(
    prompt: str,
    api_key: str,
    api_url: str,
    reference_image_path: Optional[str] = None,
    aspect_ratio: str = "9:16",
) -> Optional[str]:
    """
    调用 Gemini 生成图片，保存文件后返回可访问的 URL

    Args:
        prompt: 文字提示词
        api_key: Gemini API Key
        api_url: Gemini 生成图片 API 地址（含模型路径，不含 key）
        reference_image_path: 参考图片路径（可选，为 None 时纯文字生成）
        aspect_ratio: 图片比例，默认 1:1

    Returns:
        "/static/generated_images/xxx.png" 格式的相对 URL，失败返回 None
    """
    if not api_key:
        logger.error("Gemini API Key 未配置，无法生成图片")
        return None

    # 构建 parts：只有文字时纯文字生成，有参考图时加入 inline_data
    parts = [{"text": prompt}]

    if reference_image_path:
        try:
            img_bytes = Path(reference_image_path).read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode()
            ext = Path(reference_image_path).suffix.lower().lstrip(".")
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
            mime_type = mime_map.get(ext, "image/jpeg")
            parts.append({"inline_data": {"mime_type": mime_type, "data": img_b64}})
            logger.info(f"已加载参考图: {reference_image_path}")
        except Exception as e:
            logger.warning(f"参考图加载失败，将仅用文字生成: {e}")

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": "2K"},
        },
    }

    # 拼接 API key 到 URL
    url = f"{api_url}&key={api_key}" if "?" in api_url else f"{api_url}?key={api_key}"

    try:
        logger.info(f"调用 Gemini 图片生成 API，参考图={'有' if reference_image_path else '无'}")
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # 解析响应，找到 inlineData（图片）
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline:
                    mime = inline.get("mimeType", "image/png")
                    b64_data = inline.get("data", "")
                    if b64_data:
                        image_url = _save_base64_image(b64_data, mime)
                        logger.info(f"图片生成成功，URL: {image_url}")
                        return image_url

        logger.warning(f"Gemini 响应中未找到图片: {json.dumps(data)[:400]}")
        return None

    except httpx.HTTPStatusError as e:
        logger.error(f"Gemini API 错误 {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        logger.error(f"Gemini 图片生成异常: {e}", exc_info=True)
        return None
