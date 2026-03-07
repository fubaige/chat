import os
import asyncio
import logging
import concurrent.futures
from pathlib import Path
from typing import Optional, Dict, Any
import mimetypes
import shutil
import uuid

from app.core.config import settings
from app.core.logger import get_logger
from app.core.database import AsyncSessionLocal
from app.models.knowledge_base import KnowledgeBase
from sqlalchemy import select, update

logger = get_logger(service="indexing")

# 专用线程池：GraphRAG 索引是 CPU/IO 密集型任务，必须在独立线程中运行，
# 否则会阻塞 FastAPI 的主事件循环，导致所有 HTTP 请求卡死。
_indexing_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="graphrag-indexing"
)

class IndexingService:
    def __init__(self):
        # 明确检测操作系统
        import sys
        is_windows = sys.platform.startswith('win')
        current_os = "Windows" if is_windows else "Linux/Unix"
        logger.info(f"当前运行系统环境: {current_os}")

        # 尝试从配置加载项目目录
        raw_path = settings.GRAPHRAG_PROJECT_DIR
        configured_path = Path(raw_path)
        
        # 智能探测逻辑增强版
        should_probe = False
        
        # 1. 路径不存在
        if not configured_path.exists():
            should_probe = True
            logger.warning(f"配置路径不存在: {configured_path}")
        
        # 2. 环境不匹配检测：在 Linux 环境下使用了 Windows 路径
        elif not is_windows and ('\\' in raw_path or ':' in raw_path):
            should_probe = True
            logger.warning(f"检测到跨平台配置冲突 (当前为 {current_os}，但配置了 Windows 路径): {raw_path}")
            
        # 3. 环境不匹配检测：在 Windows 环境下使用了 Linux 路径 (较少见，但逻辑上对等)
        elif is_windows and raw_path.startswith('/'):
             # Windows 下如果配置了 / 开头的路径且不存在，也应该探测
             if not configured_path.exists():
                should_probe = True
                logger.warning(f"检测到跨平台配置冲突 (当前为 {current_os}，但配置了 Linux 路径): {raw_path}")

        if should_probe:
            logger.info("启用自动探测机制...")
            # 假设结构为 app/services/indexing_service.py -> app/graphrag
            current_file_path = Path(__file__).resolve()
            app_dir = current_file_path.parent.parent
            detected_path = app_dir / "graphrag"
            
            if detected_path.exists():
                logger.info(f"自动探测并重定向 GraphRAG 项目目录至: {detected_path}")
                self.project_dir = detected_path
            else:
                logger.error(f"严重：无法找到 GraphRAG 目录。配置路径: {configured_path}, 探测路径: {detected_path}")
                self.project_dir = configured_path
        else:
            self.project_dir = configured_path.resolve()

        self.data_dir_name = settings.GRAPHRAG_DATA_DIR
        self.data_dir = (self.project_dir / self.data_dir_name).resolve()
        
        logger.info(f"IndexingService 初始化完成。ProjectDir: {self.project_dir}")
        logger.info(f"DataDir: {self.data_dir}")
        

        # 默认配置文件
        self.default_config = 'settings.yaml'
        self.config_mapping = {
            'application/pdf': 'settings_pdf.yaml',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'settings.yaml',
            'text/plain': 'settings.yaml',
            'image/jpeg': 'settings.yaml',
            'image/png': 'settings.yaml'
        }
        
    def _load_graphrag_env(self):
        """加载 GraphRAG 专用的环境变量"""
        env_path = os.path.join(self.data_dir, ".env")
        if os.path.exists(env_path):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=True)
                logger.debug(f"已加载 GraphRAG 专用环境变量: {env_path}")
            except Exception as e:
                logger.error(f"加载 GraphRAG 环境变量失败: {e}")

    def _load_env_as_dict(self) -> Dict[str, str]:
        """将 .env 文件解析为字典，用于配置覆盖"""
        env_dict = {}
        env_path = os.path.join(self.data_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, val = line.split('=', 1)
                            env_dict[key.strip()] = val.strip().strip('"').strip("'")
            except Exception as e:
                logger.error(f"解析 .env 文件失败: {e}")
        return env_dict
        
    def _get_file_type(self, file_path: str) -> str:
        """获取文件MIME类型"""
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or 'application/octet-stream'
    
    def _get_config_file(self, file_type: str) -> str:
        """根据文件类型获取对应的配置文件"""
        return self.config_mapping.get(file_type, self.default_config)
    
    def _check_existing_index(self, file_path: str, output_dir: str) -> bool:
        """检查文件是否已经建立索引"""
        file_name = Path(file_path).stem
        index_path = os.path.join(output_dir, f"{file_name}_index")
        return os.path.exists(index_path)
    
    def _prepare_user_directories(self, user_id: int, record_id: int = None) -> tuple:
        """为用户准备输入和输出目录，每个文档独立一个子目录（按 record_id 隔离）"""
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))

        if record_id:
            # 每个文档独立目录：input/{user_uuid}/{record_id}/
            user_input_dir = os.path.join(self.data_dir, "input", user_uuid, str(record_id))
            user_output_dir = os.path.join(self.data_dir, "output", user_uuid, str(record_id))
        else:
            # 兼容旧逻辑（不传 record_id 时退回用户级目录）
            user_input_dir = os.path.join(self.data_dir, "input", user_uuid)
            user_output_dir = os.path.join(self.data_dir, "output", user_uuid)

        os.makedirs(user_input_dir, exist_ok=True)
        os.makedirs(user_output_dir, exist_ok=True)

        return user_input_dir, user_output_dir
    
    async def _extract_text_from_pdf(self, file_path: str) -> str:
        """从 PDF 提取文本（本地降级方案，MinerU 已在上层处理）：
        方案1：PyPDF2 快速提取（适用于文本型 PDF）
        方案2（兜底）：Gemini 3 大模型 OCR（扫描件/图片PDF）
        """
        # 方案1：PyPDF2 快速提取（适用于文本型 PDF）
        def _sync_extract():
            try:
                import PyPDF2
                text = ""
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        content = page.extract_text()
                        if content:
                            text += content + "\n"
                return text
            except Exception as e:
                logger.error(f"PyPDF2 提取失败: {e}")
                return ""

        text = await asyncio.to_thread(_sync_extract)
        if text and text.strip():
            logger.info(f"PyPDF2 PDF 解析成功: {len(text)} 字符")
            return text

        # 方案3：Gemini 3 大模型 OCR（扫描件/图片PDF 兜底）
        logger.warning("PyPDF2 提取为空（可能是扫描件），降级到 Gemini 3 解析")
        try:
            from app.services.gemini_service import gemini_service
            text = await gemini_service.parse_file(
                file_path,
                prompt="请完整提取该 PDF 文档中的所有文字内容，保持原文结构和段落格式，不要遗漏任何内容，不要添加总结或评论，只输出原文文字。"
            )
            if text and text.strip():
                logger.info(f"Gemini 3 PDF 解析成功: {len(text)} 字符")
                return text
        except Exception as e:
            logger.warning(f"Gemini 3 PDF 解析也失败: {e}")

        return ""

    async def _extract_text_from_docx(self, file_path: str) -> str:
        """从DOCX提取文本（在线程中执行，避免阻塞事件循环）"""
        def _sync_extract():
            try:
                import docx
                doc = docx.Document(file_path)
                return "\n".join([para.text for para in doc.paragraphs])
            except Exception as e:
                logger.error(f"DOCX extraction error: {e}")
                return ""
        return await asyncio.to_thread(_sync_extract)

    async def _prepare_input_file(self, file_path: str, file_type: str, input_dir: str) -> str:
        """准备输入文件：
        - 配置了 MinerU Token → 所有支持格式（PDF/DOCX/PPT/图片）统一走 MinerU 提取
        - 未配置 MinerU → PDF 用 PyPDF2+Gemini 降级，DOCX 用 python-docx
        """
        file_name = os.path.basename(file_path)
        base_name, _ = os.path.splitext(file_name)

        # MinerU 支持的格式
        MINERU_SUPPORTED = {
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/vnd.ms-powerpoint',
            'image/jpeg',
            'image/png',
            'image/webp',
        }

        mineru_token = settings.MINERU_API_TOKEN
        if mineru_token and mineru_token.strip() and file_type in MINERU_SUPPORTED:
            # 优先用数据库中持久化的服务器地址，其次用本次请求动态检测的地址
            server_base = (settings.SERVER_BASE_URL or self._current_server_base_url or "").rstrip("/").strip()
            if server_base:
                rel_path = file_path.replace("\\", "/").lstrip("/")
                # 对路径中每段分别编码（保留 / 分隔符，处理中文和空格）
                from urllib.parse import quote
                encoded_path = "/".join(quote(seg, safe="") for seg in rel_path.split("/"))
                file_url = f"{server_base}/{encoded_path}"
                try:
                    from app.services.mineru_service import MinerUService
                    token = mineru_token.strip().strip('"').strip("'")
                    logger.info(f"MinerU Token 前8位: {token[:8]}...，文件公网 URL: {file_url}")
                    mineru = MinerUService(token=token)
                    text = await mineru.extract_from_url(file_url)
                    if text and text.strip():
                        dest_path = os.path.join(input_dir, f"{base_name}.txt")
                        await asyncio.to_thread(self._sync_write_text, dest_path, text)
                        logger.info(f"MinerU 提取完成，保存至: {dest_path} ({len(text)} 字符)")
                        return dest_path
                except Exception as e:
                    logger.warning(f"MinerU 提取失败，降级到本地方案: {e}")
            else:
                logger.warning("未获取到服务器公网地址，跳过 MinerU")

        # --- 降级：本地提取 ---

        # DOCX → python-docx
        if file_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            text = await self._extract_text_from_docx(file_path)
            if text:
                dest_path = os.path.join(input_dir, f"{base_name}.txt")
                await asyncio.to_thread(self._sync_write_text, dest_path, text)
                logger.info(f"已提取 DOCX 文本并保存至: {dest_path}")
                return dest_path

        # PDF → PyPDF2 + Gemini 兜底
        if file_type == 'application/pdf':
            text = await self._extract_text_from_pdf(file_path)
            if text and text.strip():
                dest_path = os.path.join(input_dir, f"{base_name}.txt")
                await asyncio.to_thread(self._sync_write_text, dest_path, text)
                logger.info(f"已提取 PDF 文本并保存至: {dest_path} ({len(text)} 字符)")
                return dest_path
            else:
                logger.warning(f"PDF 文本提取为空，将尝试原始文件索引: {file_path}")

        # 其他文件类型直接复制
        dest_path = os.path.join(input_dir, file_name)
        await asyncio.to_thread(shutil.copy2, file_path, dest_path)
        logger.info(f"已将原始文件复制到输入目录: {dest_path}")
        return dest_path

    @staticmethod
    def _sync_write_text(path: str, text: str):
        """同步写文本文件"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    async def create_db_record(self, file_info: Dict[str, Any]) -> int:
        """在数据库中创建知识库记录"""
        async with AsyncSessionLocal() as session:
            kb_item = KnowledgeBase(
                user_id=file_info.get('user_id', 0),
                filename=file_info['filename'],
                original_name=file_info['original_name'],
                file_path=file_info['path'],
                file_type=file_info.get('type'),
                size=file_info.get('size'),
                status="indexing",
                index_id=file_info.get('user_uuid'),
                embedding_type=settings.EMBEDDING_TYPE,
            )
            session.add(kb_item)
            await session.commit()
            await session.refresh(kb_item)
            return kb_item.id

    async def _update_db_record(self, record_id: int, update_data: Dict[str, Any]):
        """更新数据库中的知识库记录"""
        async with AsyncSessionLocal() as session:
            stmt = update(KnowledgeBase).where(KnowledgeBase.id == record_id).values(**update_data)
            await session.execute(stmt)
            await session.commit()

    async def process_file(self, file_info: Dict[str, Any], record_id: Optional[int] = None) -> Dict[str, Any]:
        """处理单个文件的索引构建 — 异步入口，重活放到线程池执行"""
        try:
            # 1. 创建或使用已有的数据库记录
            if record_id is None:
                record_id = await self.create_db_record(file_info)

            file_path = file_info['path']
            file_type = self._get_file_type(file_path)
            user_id = file_info.get('user_id', 0)

            # 从 file_info 注入服务器公网地址（由 upload_file 接口自动检测）
            self._current_server_base_url = file_info.get('server_base_url', '')

            logger.info(f"开始处理文件: {file_path}, 类型: {file_type}, 用户ID: {user_id}")
            
            # 准备用户目录（每个文档独立 record_id 子目录）
            user_input_dir, user_output_dir = self._prepare_user_directories(user_id, record_id)

            # 准备输入文件（PDF/DOCX 提取文本转为 .txt）
            input_file_path = await self._prepare_input_file(file_path, file_type, user_input_dir)
            
            # 根据实际输入文件的扩展名决定配置（PDF 已被转为 .txt，应使用 settings.yaml）
            actual_ext = os.path.splitext(input_file_path)[1].lower()
            if actual_ext == '.pdf':
                config_file = self._get_config_file('application/pdf')
            else:
                config_file = self.default_config  # 统一用 settings.yaml
            logger.info(f"使用配置文件: {config_file} (实际输入文件: {os.path.basename(input_file_path)})")
            
            # 检查是否需要增量更新
            is_update = self._check_existing_index(input_file_path, user_output_dir)
            
            # 准备配置路径
            config_path = (self.data_dir / config_file).resolve()
            if not config_path.exists():
                config_path = (self.data_dir / self.default_config).resolve()
            if not config_path.exists():
                raise FileNotFoundError(f"Cannot find GraphRAG config file at {config_path}")
            
            # 确保加载了正确的环境变量
            self._load_graphrag_env()
            
            # 设置配置覆盖，input/output 均指向文档独立目录
            try:
                rel_input_dir = os.path.relpath(user_input_dir, self.data_dir).replace('\\', '/')
                rel_output_dir = os.path.relpath(user_output_dir, self.data_dir).replace('\\', '/')
            except ValueError:
                rel_input_dir = str(user_input_dir).replace('\\', '/')
                rel_output_dir = str(user_output_dir).replace('\\', '/')
            
            ext = os.path.splitext(input_file_path)[1].lower()
            if ext == '.pdf':
                file_type_override = 'pdf'
                pattern = r".*\.pdf$"
            else:
                file_type_override = 'text'
                pattern = r".*\.txt$"
            
            # 读取 .env 变量并显式注入配置覆盖，防止环境变量展开失败导致的 KeyError
            env_vars = self._load_env_as_dict()
            
            config_overrides = {
                'input.base_dir': rel_input_dir,
                'output.base_dir': rel_output_dir,
                'input.file_type': file_type_override,
                'input.file_pattern': pattern,
                # 显式注入 LLM 和 Embedding 配置，防止环境变量展开失效
                'models.default_chat_model.api_base': env_vars.get('GRAPHRAG_API_BASE'),
                'models.default_chat_model.api_key': env_vars.get('GRAPHRAG_API_KEY'),
                'models.default_chat_model.model': env_vars.get('GRAPHRAG_MODEL_NAME'),
                'models.default_embedding_model.api_base': env_vars.get('Embedding_API_BASE'),
                'models.default_embedding_model.api_key': env_vars.get('Embedding_API_KEY'),
                'models.default_embedding_model.model': env_vars.get('Embedding_MODEL_NAME'),
                # 索引时用绝对路径，确保和查询时路径完全一致
                'vector_store.default_vector_store.db_uri': str(Path(user_output_dir).resolve() / 'lancedb'),
            }
            
            logger.info(f"GraphRAG 配置覆盖: input_dir={rel_input_dir}, type={file_type_override}, pattern={pattern}")
            
            # ★ 核心改动：将 GraphRAG 索引构建放到独立线程中执行，
            #   避免阻塞 FastAPI 主事件循环（否则所有 HTTP 请求都会卡死）
            data_dir_str = str(Path(self.data_dir).resolve())
            config_path_str = str(Path(config_path).resolve())
            
            loop = asyncio.get_event_loop()
            index_result_list = await loop.run_in_executor(
                _indexing_executor,
                self._run_indexing_sync,
                data_dir_str,
                config_path_str,
                config_overrides,
                is_update,
                input_file_path,
                user_input_dir,
                user_output_dir,
            )
            
            result_info = {
                'id': record_id,
                'original_file_path': file_path,
                'input_file_path': input_file_path,
                'file_type': file_type,
                'config_used': config_file,
                'is_update': is_update,
                'status': 'success',
                'user_id': user_id,
                'input_dir': user_input_dir,
                'output_dir': user_output_dir
            }
            
            # 更新数据库状态
            await self._update_db_record(record_id, {"status": "success"})
            logger.info(f"数据库记录已更新为 success (ID: {record_id})")
            
            # 生成预览（可选，失败不影响主流程）
            try:
                from app.services.gemini_service import gemini_service
                preview_text = await gemini_service.parse_file(
                    input_file_path,
                    prompt="请用简洁的语言（100字以内）概括该文档或图片的核心内容。"
                )
                if preview_text:
                    result_info['preview'] = preview_text
                    await self._update_db_record(record_id, {"preview": preview_text})
            except Exception as preview_err:
                logger.warning(f"生成预览内容失败: {preview_err}")
            
            # 检查索引结果中是否有错误
            for workflow_result in index_result_list:
                if hasattr(workflow_result, 'errors') and workflow_result.errors:
                    result_info['status'] = 'error'
                    result_info['errors'] = workflow_result.errors
                    await self._update_db_record(record_id, {
                        "status": "error",
                        "error_message": "; ".join(workflow_result.errors)
                    })
                    logger.error(f"索引构建失败: {workflow_result.errors}")
            
            return result_info
            
        except Exception as e:
            logger.error(f"处理文件时发生错误: {str(e)}", exc_info=True)
            if record_id:
                await self._update_db_record(record_id, {
                    "status": "error",
                    "error_message": str(e)
                })
            return {
                'file_path': file_info.get('path'),
                'status': 'error',
                'error': str(e)
            }

    @staticmethod
    def _run_indexing_sync(
        data_dir_str: str,
        config_path_str: str,
        config_overrides: dict,
        is_update: bool,
        input_file_path: str,
        user_input_dir: str,
        user_output_dir: str,
    ) -> list:
        """在独立线程中同步执行 GraphRAG 索引构建。
        
        这个方法会被 run_in_executor 调用，运行在线程池中，
        不会阻塞 FastAPI 的主 asyncio 事件循环。
        """
        import graphrag.api as api
        from graphrag.config.load_config import load_config
        from graphrag.config.enums import IndexingMethod
        from graphrag.logger.rich_progress import RichProgressLogger
        
        # 必须在线程中创建并设置事件循环，GraphRAG 内部多处依赖 asyncio.get_event_loop()
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        
        data_dir_path = Path(data_dir_str)
        config_file_path = Path(config_path_str)
        
        logger.info(f"[线程] 正在加载 GraphRAG 配置: base_dir={data_dir_path}, config_path={config_file_path}")
        graphrag_config = load_config(data_dir_path, config_file_path, config_overrides)
        
        progress_logger = RichProgressLogger(prefix="graphrag-index")
        
        logger.info(f"[线程] 开始{'增量更新' if is_update else '构建'}索引: {input_file_path}")
        logger.info(f"[线程] 输入目录: {user_input_dir}, 输出目录: {user_output_dir}")
        
        try:
            index_result = new_loop.run_until_complete(
                api.build_index(
                    config=graphrag_config,
                    method=IndexingMethod.Standard,
                    is_update_run=is_update,
                    memory_profile=False,
                    progress_logger=progress_logger,
                )
            )
            result_list = list(index_result)
            logger.info(f"[线程] GraphRAG 索引构建完成，结果数: {len(result_list)}")
            return result_list
        finally:
            new_loop.close()
    
    async def process_directory(self, directory_path: str, user_id: int = 0) -> Dict[str, Any]:
        """处理整个目录的索引构建"""
        try:
            results = []
            for root, _, files in os.walk(directory_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        'path': file_path,
                        'original_name': file,
                        'user_id': user_id
                    }
                    result = await self.process_file(file_info)
                    results.append(result)
            
            return {
                'status': 'success',
                'processed_files': len(results),
                'results': results
            }
            
        except Exception as e:
            logger.error(f"处理目录时发生错误: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }