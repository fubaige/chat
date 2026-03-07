"""
better-auth JWT 验证中间件

验证 better-auth 签发的 JWT Token 或 Internal API Key。
优先级：Internal API Key > JWT Token

替代原有的 security.py 中的自签发 JWT 认证逻辑，
统一使用 better-auth 作为唯一认证源。
"""

import logging
from dataclasses import dataclass
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

# 使用可选的 Bearer scheme，允许请求不携带 Authorization 头
# （因为内部 API 调用使用 X-Internal-API-Key 而非 JWT）
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    """认证后的用户信息，从 JWT payload 或内部 API 请求头中提取"""

    user_id: str  # 用户 ID（JWT 的 sub 字段或 X-User-ID 请求头）
    role: str  # 用户角色（admin / user）
    is_internal: bool = False  # 是否为内部服务间调用


def verify_internal_api_key(request: Request) -> bool:
    """
    验证内部 API 密钥。

    从请求头 X-Internal-API-Key 中提取密钥，与配置中的 INTERNAL_API_KEY 比对。
    要求 INTERNAL_API_KEY 已配置且长度 ≥ 32 字符。

    Returns:
        True 如果验证通过，False 如果验证失败
    """
    api_key = request.headers.get("X-Internal-API-Key")
    if not api_key:
        return False

    configured_key = settings.INTERNAL_API_KEY
    if not configured_key or len(configured_key) < 32:
        logger.warning("INTERNAL_API_KEY 未配置或长度不足 32 字符")
        return False

    return api_key == configured_key


def verify_jwt(token: str) -> dict:
    """
    验证 better-auth 签发的 JWT。

    使用与 better-auth 相同的 SECRET_KEY（BETTER_AUTH_SECRET）和 HS256 算法验证签名。
    验证通过后返回 payload 字典，包含 sub（用户 ID）、role 等字段。

    Args:
        token: JWT token 字符串

    Returns:
        JWT payload 字典

    Raises:
        HTTPException(401): JWT 过期、签名无效或格式错误
    """
    secret = settings.BETTER_AUTH_SECRET
    if not secret:
        logger.error("BETTER_AUTH_SECRET 未配置，无法验证 JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证服务未正确配置",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = pyjwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 签名无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.DecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 格式错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.MissingRequiredClaimError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWT 缺少必要字段: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.InvalidTokenError as e:
        logger.warning(f"JWT 验证失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 无效",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """
    FastAPI 依赖：从请求中提取并验证用户身份。

    验证优先级：
    1. X-Internal-API-Key（服务间调用）— 从 X-User-ID / X-Tenant-ID 请求头提取用户信息
    2. Authorization: Bearer <JWT>（用户直接调用）— 从 JWT payload 提取用户信息
    3. 都没有则返回 401

    Returns:
        AuthenticatedUser 实例

    Raises:
        HTTPException(401): 未提供有效的认证凭据
        HTTPException(403): Internal API Key 验证失败
    """
    # 1. 优先检查 Internal API Key
    if request.headers.get("X-Internal-API-Key"):
        if verify_internal_api_key(request):
            user_id = request.headers.get("X-User-ID", "")
            role = request.headers.get("X-User-Role", "user")
            return AuthenticatedUser(
                user_id=user_id,
                role=role,
                is_internal=True,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Internal API Key 验证失败",
            )

    # 2. 检查 Bearer JWT
    if credentials and credentials.credentials:
        payload = verify_jwt(credentials.credentials)
        user_id = payload.get("sub", "")
        role = payload.get("role", "user")
        return AuthenticatedUser(
            user_id=user_id,
            role=role,
            is_internal=False,
        )

    # 3. 都没有，返回 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未提供有效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
