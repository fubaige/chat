"""微信自定义菜单 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional, Any
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.wechat_config import WechatMpConfig
from app.services.wechat_menu_service import WechatMenuService
from app.core.logger import get_logger

router = APIRouter(prefix="/wechat", tags=["微信自定义菜单"])
logger = get_logger(service="wechat_menu_api")


# ---- Pydantic schemas ----

class SubButton(BaseModel):
    type: str
    name: str
    key: Optional[str] = None
    url: Optional[str] = None
    media_id: Optional[str] = None
    appid: Optional[str] = None
    pagepath: Optional[str] = None
    article_id: Optional[str] = None


class MenuButton(BaseModel):
    name: str
    type: Optional[str] = None
    key: Optional[str] = None
    url: Optional[str] = None
    media_id: Optional[str] = None
    appid: Optional[str] = None
    pagepath: Optional[str] = None
    article_id: Optional[str] = None
    sub_button: Optional[List[SubButton]] = None


class CreateMenuRequest(BaseModel):
    button: List[MenuButton]


class UpdateAppsecretRequest(BaseModel):
    appsecret: str


# ---- helpers ----

async def _get_config_and_service(config_id: int, user: User, db: AsyncSession) -> tuple[WechatMpConfig, WechatMenuService]:
    result = await db.execute(
        select(WechatMpConfig).where(
            WechatMpConfig.id == config_id,
            WechatMpConfig.user_id == user.id
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    if not config.appsecret:
        raise HTTPException(status_code=400, detail="请先配置 AppSecret")
    service = WechatMenuService(config.appid, config.appsecret)
    return config, service


# ---- routes ----

@router.put("/configs/{config_id}/appsecret", summary="更新 AppSecret")
async def update_appsecret(
    config_id: int,
    body: UpdateAppsecretRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WechatMpConfig).where(
            WechatMpConfig.id == config_id,
            WechatMpConfig.user_id == current_user.id
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    config.appsecret = body.appsecret
    await db.commit()
    return {"message": "AppSecret 已保存"}


@router.post("/configs/{config_id}/menu", summary="创建自定义菜单")
async def create_menu(
    config_id: int,
    body: CreateMenuRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, service = await _get_config_and_service(config_id, current_user, db)
    try:
        result = await service.create_menu(body.dict(exclude_none=True))
        if result.get("errcode", 0) != 0:
            raise HTTPException(status_code=400, detail=f"微信接口错误: {result.get('errmsg')} (errcode={result.get('errcode')})")
        return {"message": "菜单创建成功", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建菜单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configs/{config_id}/menu", summary="获取自定义菜单配置")
async def get_menu(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, service = await _get_config_and_service(config_id, current_user, db)
    try:
        return await service.get_menu()
    except Exception as e:
        logger.error(f"获取菜单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configs/{config_id}/selfmenu", summary="查询当前自定义菜单信息")
async def get_selfmenu(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, service = await _get_config_and_service(config_id, current_user, db)
    try:
        return await service.get_current_selfmenu_info()
    except Exception as e:
        logger.error(f"查询菜单信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/configs/{config_id}/menu", summary="删除自定义菜单")
async def delete_menu(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, service = await _get_config_and_service(config_id, current_user, db)
    try:
        result = await service.delete_menu()
        if result.get("errcode", 0) != 0:
            raise HTTPException(status_code=400, detail=f"微信接口错误: {result.get('errmsg')} (errcode={result.get('errcode')})")
        return {"message": "菜单已删除", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除菜单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
