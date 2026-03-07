import sys
from pathlib import Path
import asyncio
from sqlalchemy import select

# Add project root to path
ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

from app.core.database import AsyncSessionLocal
from app.models.user import User

async def list_users():
    print("Checking users in database...")
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User))
            users = result.scalars().all()
            if not users:
                print("No users found in database.")
            else:
                print(f"Found {len(users)} users:")
                for u in users:
                    print(f"ID: {u.id}, Username: {u.username}, Email: {u.email}")
        except Exception as e:
            print(f"Error querying users: {e}")

if __name__ == "__main__":
    asyncio.run(list_users())
