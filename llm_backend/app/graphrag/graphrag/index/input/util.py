# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Shared column processing for structured input files."""

import logging
import re
import os
import base64
import json
import time
import requests
from typing import Any, Dict
from pathlib import Path

import pandas as pd

from graphrag.config.models.input_config import InputConfig
from graphrag.index.utils.hashing import gen_sha512_hash
from graphrag.logger.base import ProgressLogger
from graphrag.storage.pipeline_storage import PipelineStorage

log = logging.getLogger(__name__)


async def load_files(
    loader: Any,
    config: InputConfig,
    storage: PipelineStorage,
    progress: ProgressLogger | None,
) -> pd.DataFrame:
    """Load files from storage and apply a loader function."""
    files = list(
        storage.find(
            re.compile(config.file_pattern),
            progress=progress,
            file_filter=config.file_filter,
        )
    )

    if len(files) == 0:
        msg = f"No {config.file_type} files found in {config.base_dir}"
        raise ValueError(msg)

    files_loaded = []
    
    for file, group in files:
        try:
            files_loaded.append(await loader(file, group))
        except Exception as e:  # noqa: BLE001 (catching Exception is fine here)
            log.warning("Warning! Error loading file %s. Skipping...", file)
            log.warning("Error: %s", e)

    log.info(
        "Found %d %s files, loading %d", len(files), config.file_type, len(files_loaded)
    )
    result = pd.concat(files_loaded)
    total_files_log = (
        f"Total number of unfiltered {config.file_type} rows: {len(result)}"
    )
    log.info(total_files_log)
    return result


def process_data_columns(
    documents: pd.DataFrame, config: InputConfig, path: str
) -> pd.DataFrame:
    """Process configured data columns of a DataFrame.
    
    核心的关键点是：如果 config.text_column 为 None，并且 documents 中没有 text 列，那么会终止Workflow
    """

    # 检查 documents 中是否存在 id 列。如果不存在，使用 apply 方法对每一行应用 gen_sha512_hash 函数，生成一个 SHA-512 哈希值作为 id 列的值。
    if "id" not in documents.columns:
        documents["id"] = documents.apply(
            lambda x: gen_sha512_hash(x, x.keys()), axis=1
        )

    # 如果 config.text_column 不为 None 且 DataFrame 中没有 text 列，接下来会检查 config.text_column 指定的列是否存在。
    # 如果不存在，记录警告信息，且终止Workflow
    if config.text_column is not None and "text" not in documents.columns:
        if config.text_column not in documents.columns:
            log.warning(
                "text_column %s not found in csv file %s",
                config.text_column,
                path,
            )
        else:
            # 如果存在，则将 text_column 中的值提取到新的 text 列中。
            documents["text"] = documents.apply(lambda x: x[config.text_column], axis=1)

    if config.title_column is not None:
        # 检查 config.title_column 是否不为 None
        if config.title_column not in documents.columns:
            log.warning(
                "title_column %s not found in csv file %s",
                config.title_column,
                path,
            )
        else:
            documents["title"] = documents.apply(
                lambda x: x[config.title_column], axis=1
            )
    else:
        documents["title"] = documents.apply(lambda _: path, axis=1)
    return documents


def generate_image_descriptions_sync(
    config: InputConfig,
    image_dir: Path,
    output_file: Path = None,
    max_retries: int = 3,
    retry_delay: int = 2,
    max_tokens: int = 500,
    temperature: float = 0.7,
    image_info: dict = None
) -> Dict[str, str]:
    """
    使用 Gemini 视觉模型为目录中的图片生成描述。
    适配 Google AI API 格式。
    """
    api_key = config.image_description_api_key
    model = config.image_description_model
    base_url = config.image_description_base_url
    
    if not api_key or not base_url:
        log.error("Gemini API Key or Base URL is missing in config")
        return {}

    log.info(f"Using Gemini Vision model: {model} at {base_url}")
    
    if not image_dir.exists() or not image_dir.is_dir():
        log.warning(f"Image directory does not exist: {image_dir}")
        return {}
    
    image_files = []
    for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
        image_files.extend(list(image_dir.glob(f"*{ext}")))
        image_files.extend(list(image_dir.glob(f"*{ext.upper()}")))
    
    if not image_files:
        log.warning(f"No images found in {image_dir}")
        return {}
    
    log.info(f"Found {len(image_files)} images, starting Gemini analysis")
    
    descriptions = {}
    
    # 构建图片上下文映射
    context_map = {}
    if image_info and image_info.get("images"):
        for img in image_info.get("images", []):
            if img.get("path"):
                img_name = Path(img.get("path")).name
                context_map[img_name] = {
                    "context_before": img.get("context_before", ""),
                    "context_after": img.get("context_after", ""),
                    "caption": img.get("caption", "")
                }

    for i, image_path in enumerate(image_files):
        img_name = image_path.name
        log.info(f"Processing image {i+1}/{len(image_files)}: {img_name}")
        
        # 获取上下文
        ctx = context_map.get(img_name, {})
        context_text = ""
        if ctx.get("context_before"): context_text += f"图片前文: {ctx['context_before']}\n"
        if ctx.get("context_after"): context_text += f"图片后文: {ctx['context_after']}\n"
        if ctx.get("caption"): context_text += f"图片原始标题: {ctx['caption']}\n"

        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            
            # 探测 MIME 类型
            mime_type = "image/jpeg"
            if img_name.lower().endswith(".png"): mime_type = "image/png"
            elif img_name.lower().endswith(".webp"): mime_type = "image/webp"

            # 准备 Gemini 载荷
            prompt = "你是一个专业的图像描述助手。请详细描述图片中的内容，包括主要对象、场景、颜色、布局等关键信息。"
            if context_text:
                prompt += f"\n\n参考上下文：\n{context_text}\n请基于图片实际内容并参考上下文给出准确描述。"

            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_data}},
                        {"text": prompt}
                    ]
                }],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                }
            }

            url_with_key = f"{base_url}?key={api_key}"
            
            success = False
            for attempt in range(max_retries):
                try:
                    response = requests.post(url_with_key, json=payload, timeout=60)
                    if response.status_code == 200:
                        res_json = response.json()
                        desc = res_json["candidates"][0]["content"]["parts"][0]["text"]
                        descriptions[str(image_path)] = desc
                        log.info(f"Successfully described {img_name}")
                        success = True
                        break
                    else:
                        log.error(f"Gemini API error ({response.status_code}): {response.text}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))
                except Exception as e:
                    log.error(f"Gemini request failed (attempt {attempt+1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
            
            if not success:
                descriptions[str(image_path)] = "[Gemini 描述生成失败]"

        except Exception as e:
            log.error(f"Failed to process {img_name}: {e}")
            descriptions[str(image_path)] = f"[处理失败: {e}]"

        # 实时保存进度
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(descriptions, f, ensure_ascii=False, indent=2)

    return descriptions
