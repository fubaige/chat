import sys
from pathlib import Path
import asyncio
from sqlalchemy import select

ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

from app.core.database import AsyncSessionLocal
from app.services.user_service import UserService
from app.core.hashing import get_password_hash
from app.models.user import User

async def update_admin():
    print("Updating admin user...")
    async with AsyncSessionLocal() as db:
        try:
            # Find existing admin
            query = select(User).where(User.username == "admin")
            result = await db.execute(query)
            user = result.scalar_one_or_none()

            if not user:
                # Try finding by old email
                query = select(User).where(User.email == "admin@admin.com")
                result = await db.execute(query)
                user = result.scalar_one_or_none()
            
            if not user:
                print("Admin user not found. Creating new...")
                # Create if not exists (fallback)
                user = User(
                    username="admin",
                    email="admin@admin.com",
                    password_hash=get_password_hash("Admin123456")
                )
                db.add(user)
            else:
                print(f"Found user: {user.username} ({user.email})")
                # Update
                user.email = "admin@admin.com"
                user.password_hash = get_password_hash("Admin123456")
                # Ensure username is admin (if found by email)
                user.username = "admin"
            
            await db.commit()
            print("Successfully updated admin user.")
            print("Email: admin@admin.com")
            print("Password: Admin123456")
            
        except Exception as e:
            print(f"Error updating user: {e}")
            await db.rollback()

if __name__ == "__main__":
    asyncio.run(update_admin())
