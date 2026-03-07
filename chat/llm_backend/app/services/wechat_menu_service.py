"""微信自定义菜单服务 - 对接微信公众号菜单API"""
import httpx
import json
from app.core.logger import get_logger

logger = get_logger(service="wechat_menu")

WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


class WechatMenuService:
    def __init__(self, appid: str, appsecret: str):
        self.appid = appid
        self.appsecret = appsecret

    async def get_access_token(self) -> str:
        """获取微信 access_token"""
        url = f"{WECHAT_API_BASE}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.appid,
            "secret": self.appsecret,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10)
            data = resp.json()
        if "access_token" not in data:
            raise ValueError(f"获取access_token失败: {data.get('errmsg', data)}")
        return data["access_token"]

    async def create_menu(self, menu_data: dict) -> dict:
        """创建自定义菜单"""
        token = await self.get_access_token()
        url = f"{WECHAT_API_BASE}/menu/create"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                params={"access_token": token},
                json=menu_data,
                timeout=10,
            )
        result = resp.json()
        logger.info(f"创建菜单结果: {result}")
        return result

    async def get_menu(self) -> dict:
        """获取自定义菜单配置（API设置的菜单）"""
        token = await self.get_access_token()
        url = f"{WECHAT_API_BASE}/menu/get"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"access_token": token}, timeout=10)
        return resp.json()

    async def get_current_selfmenu_info(self) -> dict:
        """查询自定义菜单信息（含官网设置的菜单）"""
        token = await self.get_access_token()
        url = f"{WECHAT_API_BASE}/get_current_selfmenu_info"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"access_token": token}, timeout=10)
        return resp.json()

    async def delete_menu(self) -> dict:
        """删除自定义菜单"""
        token = await self.get_access_token()
        url = f"{WECHAT_API_BASE}/menu/delete"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"access_token": token}, timeout=10)
        result = resp.json()
        logger.info(f"删除菜单结果: {result}")
        return result
