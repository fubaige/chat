from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any
from datetime import datetime


class WechatConfigBase(BaseModel):
    """微信配置基础模型"""
    name: str = Field(..., description="配置名称")
    appid: str = Field(..., description="微信AppID")
    token: str = Field(..., description="Token令牌")
    encoding_aes_key: str = Field(..., description="消息加解密密钥")
    knowledge_base_id: Optional[str] = Field(None, description="关联的知识库ID")
    welcome_message: Optional[str] = Field(None, description="关注时的欢迎消息")
    default_reply: Optional[str] = Field(None, description="默认回复消息")
    enable_ai_reply: bool = Field(True, description="是否启用公众号/服务号接入")
    is_active: bool = Field(True, description="是否启用")


class WechatConfigCreate(WechatConfigBase):
    """创建微信配置"""
    pass


class WechatConfigUpdate(BaseModel):
    """更新微信配置"""
    name: Optional[str] = None
    appid: Optional[str] = None
    token: Optional[str] = None
    encoding_aes_key: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    welcome_message: Optional[str] = None
    default_reply: Optional[str] = None
    enable_ai_reply: Optional[bool] = None
    is_active: Optional[bool] = None


class WechatConfigResponse(WechatConfigBase):
    """微信配置响应"""
    id: int
    user_id: int
    server_url: Optional[str]
    has_appsecret: bool = False  # 是否已配置 AppSecret（不返回明文）
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='before')
    @classmethod
    def compute_has_appsecret(cls, data: Any) -> Any:
        # 兼容 ORM 对象和 dict
        if hasattr(data, 'appsecret'):
            data.__dict__['has_appsecret'] = bool(data.appsecret)
        elif isinstance(data, dict) and 'appsecret' in data:
            data['has_appsecret'] = bool(data.get('appsecret'))
        return data

    class Config:
        from_attributes = True
