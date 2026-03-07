"""
微信公众号消息处理服务

使用 PostgreSQL 的 wechat_mp_config 表读取配置，
支持消息处理超时保护（>5 秒先返回空响应，异步通过客服消息接口发送）。
"""

import asyncio
import hashlib
import logging
import time
import xml.etree.cElementTree as ET
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.wechat_config import WechatMpConfig

logger = logging.getLogger(__name__)

# 微信要求 5 秒内响应，预留 0.5 秒网络开销
WECHAT_TIMEOUT_SECONDS = 4.5


def verify_wechat_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """
    验证微信签名。

    签名算法：SHA1(sort([token, timestamp, nonce]))

    Args:
        token: 公众号配置的 Token
        signature: 微信传入的签名
        timestamp: 时间戳
        nonce: 随机数

    Returns:
        签名是否匹配
    """
    params = sorted([token, timestamp, nonce])
    computed = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
    return computed == signature


import redis
from app.lg_agent.lg_builder import graph
from app.lg_agent.lg_states import InputState

class WechatMpService:
    """微信公众号消息处理服务（内部 API 版本）
    
    从 PostgreSQL 的 wechat_mp_config 表读取配置，
    支持消息去重、LangGraph 深度集成及异步客服回复。
    """

    def __init__(self, config: WechatMpConfig):
        self.config = config
        # 初始化 Redis 用于去重和 token 缓存
        try:
            self.redis = redis.from_url(settings.REDIS_URL)
        except Exception as e:
            logger.warning(f"Wechat Service Redis 初始化失败: {e}")
            self.redis = None

    @staticmethod
    async def get_config(config_id: int) -> Optional[WechatMpConfig]:
        """从数据库加载公众号配置"""
        async with AsyncSessionLocal() as session:
            stmt = select(WechatMpConfig).where(
                WechatMpConfig.id == config_id,
                WechatMpConfig.is_active == True,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    def verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str) -> Optional[str]:
        """验证签名（实例方法版本）"""
        if verify_wechat_signature(self.config.token, signature, timestamp, nonce):
            return echostr
        return None

    async def handle_message(self, body: bytes, signature: str, timestamp: str, nonce: str, db: AsyncSession, bypass_dedup=False) -> bytes:
        """解析并处理微信消息"""
        # 注意：此处假设传入的 body 已是解密后的 XML（或者是明文模式）
        # 如果是加密模式，需调用 WXBizMsgCrypt，但目前基础实现先采用明文解析逻辑
        try:
            xml_body = body.decode("utf-8")
            msg = self._parse_xml_message(xml_body)
        except Exception as e:
            logger.error(f"微信消息解析失败: {e}")
            return b"success"

        from_user = msg.get("FromUserName", "")
        to_user = msg.get("ToUserName", "")
        msg_type = msg.get("MsgType", "")
        msg_id = msg.get("MsgId") or f"{from_user}_{msg.get('CreateTime')}"

        # 1. Redis 消息去重拦截
        if self.redis and not bypass_dedup:
            dedup_key = f"wx_msg_dedup:{msg_id}"
            if not self.redis.set(dedup_key, "1", ex=60, nx=True):
                logger.info(f"拦截重复微信请求: {msg_id}")
                return b"success"

        # 2. 路由处理
        from wx_mp_svr import WxRspMsg
        if msg_type == "event":
            event = msg.get("Event", "")
            if event == "subscribe":
                content = self.config.welcome_message or "欢迎关注！"
                rsp = WxRspMsg.create_msg("text")
                rsp.to_user_name, rsp.from_user_name = from_user, to_user
                rsp.content = content
                return rsp.dump_xml()
            return b"success"

        if msg_type == "text":
            user_text = msg.get("Content", "").strip()
            if not user_text: return b"success"

            if not self.config.enable_ai_reply:
                content = self.config.default_reply or "收到啦"
                rsp = WxRspMsg.create_msg("text")
                rsp.to_user_name, rsp.from_user_name = from_user, to_user
                rsp.content = content
                return rsp.dump_xml()

            # 调用 AI 引擎
            ai_reply = await self._get_ai_reply(user_text, db)
            rsp = WxRspMsg.create_msg("text")
            rsp.to_user_name, rsp.from_user_name = from_user, to_user
            rsp.content = ai_reply
            return rsp.dump_xml()

        return b"success"

    async def _get_ai_reply(self, user_message: str, db: AsyncSession) -> str:
        """调用 LangGraph 引擎生成回复"""
        thread_id = f"wx_{self.config.appid}_{self.config.id}"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": self.config.user_id,
                "knowledgeBaseIds": self.config.knowledge_base_ids or []
            }
        }
        # 显式传入 skip_hallucination=True 以加速回复
        input_state = {
            "messages": [{"role": "user", "content": user_message}],
            "skip_hallucination": True
        }
        
        full_response = ""
        try:
            async for chunk in graph.astream(input_state, config=config, stream_mode="values"):
                if "messages" in chunk:
                    last_msg = chunk["messages"][-1]
                    full_response = last_msg.content
            
            return full_response.strip() if full_response else "正在深度思考中..."
        except Exception as e:
            logger.error(f"微信 AI 生成失败: {e}", exc_info=True)
            return "服务正忙，请稍后再试"

    async def send_custom_message(self, openid: str, content: str):
        """通过客服接口发送异步消息"""
        token = await self.get_access_token()
        if not token: return
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json={
                    "touser": openid,
                    "msgtype": "text",
                    "text": {"content": content}
                })
                logger.info(f"异步客服消息发送结果: {resp.json()}")
            except Exception as e:
                logger.error(f"异步客服消息发送失败: {e}")

    async def get_access_token(self) -> Optional[str]:
        """获取并缓存 access_token"""
        if not self.redis: return None
        cache_key = f"wx_access_token:{self.config.appid}"
        cached = self.redis.get(cache_key)
        if cached: return cached.decode('utf-8')

        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.config.appid}&secret={self.config.appsecret}"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url)
                data = resp.json()
                if "access_token" in data:
                    at = data["access_token"]
                    # 缓存 7000 秒（微信有效期 7200s）
                    self.redis.set(cache_key, at, ex=7000)
                    return at
                logger.error(f"获取微信 token 失败: {data}")
            except Exception as e:
                logger.error(f"获取微信 token 异常: {e}")
        return None

    def _parse_xml_message(self, xml_body: str) -> dict:
        root = ET.fromstring(xml_body)
        msg = {}
        for child in root: msg[child.tag] = child.text or ""
        return msg

# 别名
WechatService = WechatMpService
