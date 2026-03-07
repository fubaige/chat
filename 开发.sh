#!/bin/bash

# Cloud Startup Script for Backend Service
# Usage: ./1.sh

echo "==========================================="
echo "   Smart Customer Service Backend Startup  "
echo "==========================================="

# 0. Check Neo4j service status
echo "[0/5] Checking Neo4j service..."
if command -v neo4j &> /dev/null; then
    if command -v systemctl &> /dev/null && systemctl is-active --quiet neo4j 2>/dev/null; then
        echo "      Neo4j is running ✓"
    elif pgrep -f "neo4j" > /dev/null 2>&1; then
        echo "      Neo4j process detected ✓"
    else
        echo "      [WARN] Neo4j is installed but not running."
        echo "      Attempting to start Neo4j..."
        systemctl start neo4j 2>/dev/null || neo4j start 2>/dev/null || true
        sleep 3
        if pgrep -f "neo4j" > /dev/null 2>&1; then
            echo "      Neo4j started ✓"
        else
            echo "      [WARN] Could not start Neo4j. Run: systemctl start neo4j"
            echo "             GraphRAG features may not work without Neo4j."
        fi
    fi
else
    echo "      [WARN] Neo4j not found. GraphRAG features will be unavailable."
    echo "             To install: run ./deploy.sh"
fi

# 1. Kill existing backend processes to prevent port conflicts
echo "[1/5] Stopping existing services..."
pkill -f "python run.py" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "main:app" 2>/dev/null || true
# 杀死占用端口的进程
for PORT in 8000; do
    if fuser "$PORT/tcp" > /dev/null 2>&1; then
        echo "      Killing process on port $PORT..."
        fuser -k "$PORT/tcp" > /dev/null 2>&1 || true
    fi
done
sleep 1
echo "      Services stopped."

# 2. Set PYTHONPATH
CURRENT_DIR=$(pwd)
APP_DIR="$CURRENT_DIR/llm_backend/app"
export PYTHONPATH="$APP_DIR:$PYTHONPATH"
echo "[2/5] Configured PYTHONPATH: $APP_DIR"

# 3. Enter backend directory
cd llm_backend || { echo "Error: llm_backend directory not found!"; exit 1; }

# 4. Activate virtual environment if it exists
if [ -d "../venv" ]; then
    echo "[3/5] Activating virtual environment (../venv)..."
    source ../venv/bin/activate
elif [ -d "venv" ]; then
    echo "[3/5] Activating virtual environment (venv)..."
    source venv/bin/activate
else
    echo "[3/5] No virtual environment found, using system python..."
fi

# 4.1 Check and install dependencies if needed
echo "[3.5/5] Checking and repairing python dependencies..."
if [ -f "../requirements.txt" ]; then
    echo "      Ensuring all dependencies in requirements.txt are installed..."
    python -m pip install -r ../requirements.txt || echo "      [WARN] Dependency repair failed, trying to continue..."
elif [ -f "requirements.txt" ]; then
    echo "      Ensuring all dependencies in requirements.txt are installed..."
    python -m pip install -r requirements.txt || echo "      [WARN] Dependency repair failed, trying to continue..."
else
    echo "      [WARN] requirements.txt not found! Skipping auto-repair."
fi

# 4.2 自动建表（同步所有模型到数据库）
echo "[4/5] Syncing database tables..."
python - <<'PYEOF'
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def create_tables():
    from app.core.database import engine, Base
    import app.models  # noqa: 触发所有模型注册
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("      Database tables synced successfully.")

        # 补列迁移（create_all 不给已有表加新列）
        async with engine.begin() as conn:
            await conn.run_sync(_migrate_columns)
        print("      Column migration done.")
    except Exception as e:
        print(f"      Warning: Failed to sync tables: {e}")
    finally:
        await engine.dispose()

def _migrate_columns(conn):
    from sqlalchemy import text, inspect
    inspector = inspect(conn)
    migrations = [
        ("wechat_configs", "appsecret", "VARCHAR(255)"),
    ]
    for table, column, col_def in migrations:
        try:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                print(f"      Migrated: {table}.{column} added.")
        except Exception as e:
            print(f"      Skip migration {table}.{column}: {e}")

asyncio.run(create_tables())
PYEOF

# 5. Start the backend service
echo "[5/5] Starting backend service..."
nohup python run.py > backend.log 2>&1 &

PID=$!
echo "      Backend started with PID: $PID"
echo "==========================================="
echo "Logs: llm_backend/backend.log"
echo "Tailing logs now (Ctrl+C to exit tail, server keeps running)..."
echo "==========================================="

sleep 2
tail -f backend.log
