from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.wechat_config import WechatConfig
from app.schemas.wechat import WechatConfigCreate, WechatConfigUpdate, WechatConfigResponse
from app.services.wechat_service import WechatService
from app.core.logger import get_logger

router = APIRouter(prefix="/wechat", tags=["微信集成"])
logger = get_logger(service="wechat_api")


@router.post("/configs", response_model=WechatConfigResponse, summary="创建微信配置", description="创建微信公众号/服务号的自动回复配置，创建后获得服务器回调 URL")
async def create_wechat_config(
    config: WechatConfigCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """创建微信公众号/服务号配置"""
    try:
        # 创建配置
        db_config = WechatConfig(
            user_id=current_user.id,
            name=config.name,
            appid=config.appid,
            token=config.token,
            encoding_aes_key=config.encoding_aes_key,
            knowledge_base_id=config.knowledge_base_id,
            welcome_message=config.welcome_message,
            default_reply=config.default_reply,
            enable_ai_reply=config.enable_ai_reply,
            is_active=config.is_active
        )
        
        db.add(db_config)
        await db.flush()  # 获取ID但不提交
        
        # 生成服务器URL - 使用固定路径 /wx_mp_cb
        db_config.server_url = f"/wx_mp_cb?config_id={db_config.id}"
        
        await db.commit()
        await db.refresh(db_config)
        
        logger.info(f"用户 {current_user.id} 创建微信配置: {db_config.id}")
        return db_config
    except Exception as e:
        logger.error(f"创建微信配置失败: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@router.get("/configs", response_model=List[WechatConfigResponse], summary="获取微信配置列表", description="获取当前用户的所有微信公众号配置")
async def get_wechat_configs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取当前用户的所有微信配置"""
    try:
        result = await db.execute(
            select(WechatConfig).where(WechatConfig.user_id == current_user.id)
        )
        configs = result.scalars().all()
        return configs
    except Exception as e:
        logger.error(f"获取微信配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/configs/{config_id}", response_model=WechatConfigResponse, summary="获取单个微信配置", description="根据配置 ID 获取指定的微信配置详情")
async def get_wechat_config(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取指定的微信配置"""
    try:
        result = await db.execute(
            select(WechatConfig).where(
                WechatConfig.id == config_id,
                WechatConfig.user_id == current_user.id
            )
        )
        config = result.scalar_one_or_none()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        return config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取微信配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.put("/configs/{config_id}", response_model=WechatConfigResponse, summary="更新微信配置", description="更新指定微信配置的参数，如 Token、AES Key、欢迎语等")
async def update_wechat_config(
    config_id: int,
    config_update: WechatConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新微信配置"""
    try:
        result = await db.execute(
            select(WechatConfig).where(
                WechatConfig.id == config_id,
                WechatConfig.user_id == current_user.id
            )
        )
        config = result.scalar_one_or_none()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        # 更新字段
        update_data = config_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(config, field, value)
        
        await db.commit()
        await db.refresh(config)
        
        logger.info(f"用户 {current_user.id} 更新微信配置: {config_id}")
        return config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新微信配置失败: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.delete("/configs/{config_id}", summary="删除微信配置", description="删除指定的微信公众号配置")
async def delete_wechat_config(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除微信配置"""
    try:
        result = await db.execute(
            select(WechatConfig).where(
                WechatConfig.id == config_id,
                WechatConfig.user_id == current_user.id
            )
        )
        config = result.scalar_one_or_none()
        
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        await db.delete(config)
        await db.commit()
        
        logger.info(f"用户 {current_user.id} 删除微信配置: {config_id}")
        return {"message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除微信配置失败: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")


@router.get("/callback")
async def wechat_callback_get(
    request: Request,
    config_id: int = Query(..., description="配置ID"),
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """微信服务器验证回调（GET请求）"""
    try:
        # 获取配置
        result = await db.execute(
            select(WechatConfig).where(WechatConfig.id == config_id)
        )
        config = result.scalar_one_or_none()
        
        if not config or not config.is_active:
            raise HTTPException(status_code=404, detail="配置不存在或未启用")
        
        # 验证签名
        wechat_service = WechatService(config)
        verified_echostr = wechat_service.verify_signature(signature, timestamp, nonce, echostr)
        
        if verified_echostr:
            return verified_echostr
        else:
            raise HTTPException(status_code=403, detail="签名验证失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"微信回调验证失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/callback")
async def wechat_callback_post(
    request: Request,
    config_id: int = Query(..., description="配置ID"),
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """微信消息推送回调（POST请求）"""
    try:
        # 获取配置
        result = await db.execute(
            select(WechatConfig).where(WechatConfig.id == config_id)
        )
        config = result.scalar_one_or_none()
        
        if not config or not config.is_active:
            raise HTTPException(status_code=404, detail="配置不存在或未启用")
        
        # 获取请求体
        body = await request.body()
        
        # 处理消息
        wechat_service = WechatService(config)
        response = await wechat_service.handle_message(body, signature, timestamp, nonce, db)
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"微信消息处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"消息处理失败: {str(e)}")
