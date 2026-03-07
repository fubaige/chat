from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.schemas.user import UserCreate, UserResponse, Token, UserLogin
from app.services.user_service import UserService
from datetime import timedelta
from app.core.config import settings
from app.models.user import User

router = APIRouter()

@router.post("/register", response_model=UserResponse, tags=["用户认证"], summary="用户注册", description="注册新用户账号，注册成功后自动生成专属 API 密钥")
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    user_service = UserService(db)
    try:
        new_user = await user_service.create_user(user_data)
        return new_user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/token", response_model=Token, tags=["用户认证"], summary="用户登录", description="使用邮箱和密码登录，返回 JWT Token。将 access_token 填入右上角 Authorize 按钮即可调用需要认证的接口")
async def login(user_data: UserLogin, db: AsyncSession = Depends(get_db)):
    from app.core.logger import get_logger
    logger = get_logger(service="auth_debug")
    logger.info(f"Login attempt raw: email={repr(user_data.email)}, password_val={user_data.password[:2]}*** (len={len(user_data.password)})")

    user_service = UserService(db)
    user = await user_service.authenticate_user(user_data.email, user_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
   
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "user_id": user.id}, 
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/users/me", response_model=UserResponse, tags=["用户认证"], summary="获取当前用户信息", description="获取当前已登录用户的详细信息，包括用户名、邮箱、角色和专属 API 密钥")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户的信息"""
    return current_user