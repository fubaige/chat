"""
MinerU API 文档提取服务
使用单任务接口：POST /api/v4/extract/task（传入文件公网 URL）
支持 PDF、DOC、DOCX、PPT、PPTX、图片等格式，启用 vlm OCR
"""

import asyncio
import time
import httpx
from app.core.logger import get_logger

logger = get_logger(service="mineru")

MINERU_API_BASE = "https://mineru.net/api/v4"
POLL_INTERVAL = 8       # 轮询间隔（秒）
MAX_WAIT_SECONDS = 600  # 最大等待时间（秒）


class MinerUService:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    async def extract_from_url(self, file_url: str) -> str:
        """
        通过公网 URL 提交 MinerU 提取任务，返回 markdown 文本。
        接口：POST /api/v4/extract/task
        """
        logger.info(f"MinerU 提交任务，文件 URL: {file_url}")

        async with httpx.AsyncClient(timeout=60) as client:
            # 提交任务
            payload = {"url": file_url, "model_version": "vlm"}
            resp = await client.post(
                f"{MINERU_API_BASE}/extract/task",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(f"MinerU 提交任务失败: {data}")

            task_id = data.get("data", {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"MinerU 未返回 task_id: {data}")

            logger.info(f"MinerU 任务已提交，task_id={task_id}")

            # 轮询任务状态
            return await self._poll_task(client, task_id)

    async def _poll_task(self, client: httpx.AsyncClient, task_id: str) -> str:
        """轮询任务直到完成，返回 markdown 文本"""
        status_url = f"{MINERU_API_BASE}/extract/task/{task_id}"
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > MAX_WAIT_SECONDS:
                raise TimeoutError(f"MinerU 任务超时（{MAX_WAIT_SECONDS}s），task_id={task_id}")

            await asyncio.sleep(POLL_INTERVAL)

            resp = await client.get(status_url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            task_data = data.get("data", {})
            state = str(task_data.get("state") or task_data.get("status") or "").lower()
            logger.info(f"MinerU 任务状态: {state}（已等待 {elapsed:.0f}s）task_id={task_id}")

            if state in ("done", "success", "finished", "completed"):
                return await self._extract_markdown(client, task_data)
            elif state in ("failed", "error"):
                err = task_data.get("err_msg") or task_data.get("message") or "未知错误"
                raise RuntimeError(f"MinerU 任务失败: {err}")
            # pending / running / processing → 继续等待

    async def _extract_markdown(self, client: httpx.AsyncClient, task_data: dict) -> str:
        """从任务结果中提取 markdown 内容"""
        # 结构1：full_zip_url（zip 包含 .md 文件）
        zip_url = task_data.get("full_zip_url") or task_data.get("zip_url")
        if zip_url:
            return await self._download_markdown_from_zip(client, zip_url)

        # 结构2：直接有 markdown_url
        md_url = task_data.get("markdown_url") or task_data.get("md_url")
        if md_url:
            logger.info(f"MinerU 下载 markdown: {md_url[:80]}...")
            resp = await client.get(md_url, timeout=60)
            resp.raise_for_status()
            return resp.text

        # 结构3：result 列表
        results = task_data.get("result") or task_data.get("results") or []
        if isinstance(results, list) and results:
            first = results[0]
            zip_url = first.get("full_zip_url") or first.get("zip_url")
            if zip_url:
                return await self._download_markdown_from_zip(client, zip_url)
            md_url = first.get("markdown_url") or first.get("md_url")
            if md_url:
                resp = await client.get(md_url, timeout=60)
                resp.raise_for_status()
                return resp.text

        # 结构4：直接有 markdown/content 字段
        content = task_data.get("markdown") or task_data.get("content") or task_data.get("text")
        if content:
            return content

        logger.warning(f"MinerU 无法解析结果结构，完整数据: {task_data}")
        raise RuntimeError(f"MinerU 结果结构未知，无法提取 markdown")

    async def _download_markdown_from_zip(self, client: httpx.AsyncClient, zip_url: str) -> str:
        """从 zip 包中提取 .md 文件内容"""
        import io
        import zipfile

        logger.info(f"MinerU 下载 zip 包: {zip_url[:80]}...")
        resp = await client.get(zip_url, timeout=120)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            md_files = [n for n in zf.namelist() if n.endswith(".md")]
            if not md_files:
                raise RuntimeError("MinerU zip 包中未找到 .md 文件")
            with zf.open(md_files[0]) as f:
                content = f.read().decode("utf-8")
                logger.info(f"MinerU 从 zip 提取 markdown 成功: {len(content)} 字符")
                return content
