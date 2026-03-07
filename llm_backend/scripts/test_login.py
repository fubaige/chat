import sys
from pathlib import Path
import asyncio
from sqlalchemy import select

ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.hashing import verify_password
from app.services.user_service import UserService

async def test_login():
    email = "admin@admin.com"
    password = "Admin123456"
    
    print(f"Testing login for {email} ...")
    
    async with AsyncSessionLocal() as db:
        # Check user in DB
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            print(f"User with email {email} NOT FOUND in DB.")
            # Check if 'admin' exists with other email
            r2 = await db.execute(select(User).where(User.username == "admin"))
            u2 = r2.scalar_one_or_none()
            if u2:
                print(f"User 'admin' exists but has email: {u2.email}")
            return

        print(f"User found: ID={user.id}, Username={user.username}, Email={user.email}")
        print(f"Password Hash: {user.password_hash}")
        
        # Verify password
        is_valid = verify_password(password, user.password_hash)
        
        if is_valid:
             print("LOGIN SUCCESSFUL VALIDATION")
             sys.exit(0)
        else:
             print("LOGIN FAILED VALIDATION")
             sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_login())
