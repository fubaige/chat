from wx_mp_svr import WxMpReqMsg, WxMpRspMsg
from wx_crypt import WXBizMsgCrypt, WxChannel_Mp
import xml.etree.cElementTree as ET
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import get_logger
from app.models.wechat_config import WechatConfig
from typing import Optional, Dict, Any
import redis
import httpx
import json
import asyncio
from app.core.config import settings
from app.lg_agent.lg_builder import graph
from app.lg_agent.lg_states import InputState

logger = get_logger(service="wechat_service")


class WechatService:
    """微信公众号/服务号消息处理服务"""
    
    def __init__(self, config: WechatConfig):
        self.config = config
        self.wx_crypt = WXBizMsgCrypt(
            config.token,
            config.encoding_aes_key,
            config.appid,
            WxChannel_Mp
        )
        # 初始化 Redis 客户端
        try:
            self.redis = redis.from_url(settings.REDIS_URL)
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            self.redis = None
    
    def verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str) -> Optional[str]:
        """验证微信服务器签名"""
        try:
            logger.info(f"开始验证签名: token={self.config.token[:8]}..., signature={signature}, timestamp={timestamp}, nonce={nonce}")
            
            ret, decrypted_echostr = self.wx_crypt.VerifyURL(
                signature, timestamp, nonce, echostr
            )
            
            if ret == 0:
                if isinstance(decrypted_echostr, bytes):
                    decrypted_echostr = decrypted_echostr.decode('utf-8')
                return decrypted_echostr
            else:
                logger.error(f"签名验证失败，错误码: {ret}")
                return None
        except Exception as e:
            logger.error(f"签名验证异常: {str(e)}", exc_info=True)
            return None
    
    async def handle_message(
        self,
        body: bytes,
        signature: str,
        timestamp: str,
        nonce: str,
        db: AsyncSession,
        bypass_dedup: bool = False
    ) -> bytes:
        """处理微信消息"""
        try:
            # 解密消息
            ret, xml_content = self.wx_crypt.DecryptMsg(body, signature, timestamp, nonce)
            if ret != 0:
                logger.error(f"消息解密失败，错误码: {ret}")
                return self._create_empty_response()
            
            # 解析XML
            xml_tree = ET.fromstring(xml_content)
            req_msg = WxMpReqMsg.create_msg(xml_tree)
            
            # 消息排重：使用 msg_id 或 (FromUserName + CreateTime)
            if self.redis and not bypass_dedup:
                msg_id = getattr(req_msg, 'msg_id', None)
                if not msg_id:
                    msg_id = f"{req_msg.from_user_name}_{req_msg.create_time}"
                
                dedup_key = f"wx_msg_dedup:{msg_id}"
                if self.redis.set(dedup_key, "1", ex=60, nx=True):
                    logger.debug(f"新消息进入: {msg_id}")
                else:
                    logger.info(f"拦截重试消息: {msg_id}")
                    return self._create_empty_response()
            
            # 根据消息类型处理
            if req_msg.msg_type == "event":
                rsp_msg = await self._handle_event(req_msg, db)
            else:
                rsp_msg = await self._handle_text_message(req_msg, db)
            
            # 加密响应
            return self._encrypt_response(rsp_msg, timestamp, nonce)
        
        except Exception as e:
            logger.error(f"消息处理异常: {str(e)}", exc_info=True)
            return self._create_empty_response()
    
    async def _handle_event(self, req_msg: WxMpReqMsg, db: AsyncSession) -> WxMpRspMsg:
        """处理事件消息"""
        try:
            if hasattr(req_msg, 'event') and req_msg.event == "subscribe":
                rsp_msg = WxMpRspMsg.create_msg("text")
                rsp_msg.to_user_name = req_msg.from_user_name
                rsp_msg.from_user_name = req_msg.to_user_name
                rsp_msg.content = self.config.welcome_message or "欢迎关注！有什么可以帮助您的吗？"
                return rsp_msg
            
            return WxMpRspMsg.create_msg("text")
        except Exception as e:
            logger.error(f"事件处理异常: {str(e)}")
            return self._create_default_response(req_msg)
    
    async def _handle_text_message(self, req_msg: WxMpReqMsg, db: AsyncSession) -> WxMpRspMsg:
        """处理文本消息"""
        try:
            rsp_msg = WxMpRspMsg.create_msg("text")
            rsp_msg.to_user_name = req_msg.from_user_name
            rsp_msg.from_user_name = req_msg.to_user_name
            
            if self.config.enable_ai_reply and hasattr(req_msg, 'content'):
                ai_reply = await self._get_ai_reply(req_msg.content, db)
                rsp_msg.content = ai_reply
            else:
                rsp_msg.content = self.config.default_reply or "收到您的消息了！"
            
            return rsp_msg
        except Exception as e:
            logger.error(f"文本消息处理异常: {str(e)}")
            return self._create_default_response(req_msg)
    
    async def _get_ai_reply(self, user_message: str, db: AsyncSession) -> str:
        """调用网页端同款 LangGraph 引擎生成回复"""
        try:
            logger.info(f"微信端开始 LangGraph 对话流程: {user_message}")
            
            thread_id = f"wx_{self.config.appid}_{self.config.id}"
            thread_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": self.config.user_id
                }
            }
            
            input_state = {
                "messages": [{"role": "user", "content": user_message}],
                "skip_hallucination": True
            }
            full_response = ""
            async for chunk in graph.astream(input_state, config=thread_config, stream_mode="values"):
                if "messages" in chunk:
                    last_msg = chunk["messages"][-1]
                    if last_msg.type == "ai":
                        full_response = last_msg.content

            if full_response:
                return full_response.strip()
            
            return "抱歉，我现在无法回答您的问题，请稍后再试。"
        except Exception as e:
            logger.error(f"LangGraph 调用异常: {str(e)}", exc_info=True)
            return "服务正忙，请稍后再试。"

    async def get_access_token(self) -> Optional[str]:
        """获取并缓存 AccessToken"""
        if not self.redis: return None
        token_key = f"wx_token:{self.config.appid}"
        cached_token = self.redis.get(token_key)
        if cached_token: return cached_token.decode('utf-8')
            
        if not self.config.appsecret: return None
            
        try:
            url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.config.appid}&secret={self.config.appsecret}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                data = resp.json()
                if "access_token" in data:
                    token = data["access_token"]
                    self.redis.set(token_key, token, ex=7000)
                    return token
        except Exception:
            pass
        return None

    async def send_custom_message(self, openid: str, content: str):
        """发送客服消息（异步回复）"""
        token = await self.get_access_token()
        if not token: return
        
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        payload = {"touser": openid, "msgtype": "text", "text": {"content": content}}
        try:
            async with httpx.AsyncClient() as client:
                await client.post(url, json=payload)
        except Exception:
            pass

    def _create_default_response(self, req_msg: WxMpReqMsg) -> WxMpRspMsg:
        """创建默认响应"""
        rsp_msg = WxMpRspMsg.create_msg("text")
        rsp_msg.to_user_name = req_msg.from_user_name
        rsp_msg.from_user_name = req_msg.to_user_name
        rsp_msg.content = self.config.default_reply or "收到您的消息了！"
        return rsp_msg
    
    def _encrypt_response(self, rsp_msg: WxMpRspMsg, timestamp: str, nonce: str) -> bytes:
        """加密响应消息"""
        try:
            msg_xml = rsp_msg.dump_xml()
            logger.info(f"待加密发送的微信XML响应: {msg_xml.decode('utf-8') if isinstance(msg_xml, bytes) else str(msg_xml)}")
            ret, encrypted_msg = self.wx_crypt.EncryptMsg(msg_xml, nonce, timestamp)
            if ret == 0:
                return encrypted_msg
            return self._create_empty_response()
        except Exception:
            return self._create_empty_response()
    
    def _create_empty_response(self) -> bytes:
        """创建空响应"""
        return b"success"
