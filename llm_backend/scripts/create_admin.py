import sys
from pathlib import Path
import asyncio

ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

from app.core.database import AsyncSessionLocal
from app.services.user_service import UserService
from app.schemas.user import UserCreate

async def create_admin():
    print("Creating admin user...")
    async with AsyncSessionLocal() as db:
        user_service = UserService(db)
        try:
            # Check by email first
            existing_email = await user_service.get_user_by_email("admin@admin.com")
            
            if existing_email:
                print("User admin@admin.com already exists.")
                return

            user = await user_service.create_user(UserCreate(
                username="admin",
                email="admin@admin.com",
                password="password123"
            ))
            print(f"Successfully created user: {user.username}")
            print(f"Email: {user.email}")
            print("Password: password123")
        except Exception as e:
            print(f"Error creating user: {e}")

if __name__ == "__main__":
    asyncio.run(create_admin())
