"""
重置 admin@admin.com 的密码为 Aa2135689
运行方式: cd llm_backend && python reset_admin_password.py
"""
import asyncio
import bcrypt
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = "mysql+aiomysql://chat_aigcqun_cn:f6WzA5XenzCPh4wS@103.36.221.102:3306/chat_aigcqun_cn"

EMAIL = "admin@admin.com"
NEW_PASSWORD = "Aa2135689"  # 明文密码，与前端登录保持一致（前端不做SHA256）

async def reset_password():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 生成 bcrypt 哈希
    hashed = bcrypt.hashpw(NEW_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, email, password_hash FROM users WHERE email = :email"),
            {"email": EMAIL}
        )
        user = result.fetchone()
        if not user:
            print(f"❌ 用户 {EMAIL} 不存在")
            return

        print(f"✅ 找到用户: id={user.id}, email={user.email}")
        print(f"   旧 hash: {user.password_hash[:30]}...")

        await session.execute(
            text("UPDATE users SET password_hash = :hash WHERE email = :email"),
            {"hash": hashed, "email": EMAIL}
        )
        await session.commit()
        print(f"✅ 密码已重置为: {NEW_PASSWORD}")
        print(f"   新 hash: {hashed[:30]}...")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_password())
