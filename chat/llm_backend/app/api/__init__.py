from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.wechat import router as wechat_router
from app.api.wechat_menu import router as wechat_menu_router
from app.api.agent_config import router as agent_config_router
from app.api.internal import router as internal_router

# 创建主路由，所有可用的参数：https://fastapi.tiangolo.com/reference/apirouter/?h=apirouter#fastapi.APIRouter--example
api_router = APIRouter()

# 注册所有子路由，不使用前缀
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(wechat_router, tags=["wechat"])
api_router.include_router(wechat_menu_router, tags=["wechat_menu"])
api_router.include_router(agent_config_router, tags=["智能体配置"])

# 内部 API 路由单独导出，在 main.py 中直接注册到 app（不经过 /api 前缀）