"""
Gemini 图片生成服务
支持：纯文字生成图片 / 参考图+提示词生成图片
生成的 base64 图片上传到阿里云 OSS，返回公网可访问的 URL
"""
import base64
import httpx
import json
import uuid
import oss2
from io import BytesIO
from pathlib import Path
from typing import Optional
from app.core.logger import get_logger
from app.core.config import settings

logger = get_logger(service="gemini_image_gen")


def _get_oss_bucket() -> Optional[oss2.Bucket]:
    """获取 OSS Bucket 实例，配置不完整时返回 None"""
    access_key_id = settings.OSS_ACCESS_KEY_ID or settings.ALIYUN_ACCESS_KEY_ID
    access_key_secret = settings.OSS_ACCESS_KEY_SECRET or settings.ALIYUN_ACCESS_KEY_SECRET
    bucket_name = settings.OSS_BUCKET
    endpoint = settings.OSS_ENDPOINT

    if not all([access_key_id, access_key_secret, bucket_name, endpoint]):
        logger.warning("OSS 配置不完整，无法上传到云存储")
        return None

    auth = oss2.Auth(access_key_id, access_key_secret)
    return oss2.Bucket(auth, f"https://{endpoint}", bucket_name)


def _upload_to_oss(img_bytes: bytes, ext: str) -> Optional[str]:
    """将图片字节上传到 OSS，返回公网 URL，失败返回 None"""
    bucket = _get_oss_bucket()
    if not bucket:
        return None

    filename = f"{uuid.uuid4().hex}.{ext}"
    key = f"generated_images/{filename}"

    try:
        bucket.put_object(key, BytesIO(img_bytes), headers={
            "Content-Type": f"image/{ext}" if ext != "jpg" else "image/jpeg",
        })
        # 构建公网访问 URL
        endpoint = settings.OSS_ENDPOINT
        bucket_name = settings.OSS_BUCKET
        url = f"https://{bucket_name}.{endpoint}/{key}"
        logger.info(f"图片已上传到 OSS: {url}")
        return url
    except Exception as e:
        logger.error(f"上传图片到 OSS 失败: {e}")
        return None


# 本地保存目录（OSS 上传失败时的降级方案）
GENERATED_IMAGE_DIR = Path("static/generated_images")


def _save_base64_image_local(b64_data: str, mime: str) -> str:
    """降级方案：将 base64 图片保存到本地，返回相对 URL"""
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
    logger.info(f"图片已保存到本地（降级）: {file_path}")
    return f"/static/generated_images/{filename}"


def _save_base64_image(b64_data: str, mime: str) -> str:
    """
    将 base64 图片数据保存：优先上传到 OSS，失败则保存到本地
    返回可访问的 URL（OSS 公网 URL 或本地相对路径）
    """
    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }
    ext = ext_map.get(mime, "png")
    img_bytes = base64.b64decode(b64_data)

    # 优先上传到 OSS
    oss_url = _upload_to_oss(img_bytes, ext)
    if oss_url:
        return oss_url

    # 降级：保存到本地
    return _save_base64_image_local(b64_data, mime)


async def generate_image(
    prompt: str,
    api_key: str,
    api_url: str,
    reference_image_path: Optional[str] = None,
    aspect_ratio: str = "9:16",
) -> Optional[str]:
    """
    调用 Gemini 生成图片，上传到 OSS 后返回公网 URL

    Args:
        prompt: 文字提示词
        api_key: Gemini API Key
        api_url: Gemini 生成图片 API 地址（含模型路径，不含 key）
        reference_image_path: 参考图片路径（可选，为 None 时纯文字生成）
        aspect_ratio: 图片比例，默认 9:16

    Returns:
        OSS 公网 URL 或本地相对 URL，失败返回 None
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
