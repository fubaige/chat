#!/bin/bash
# 生产环境启动脚本 - 支持后台运行

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目目录
PROJECT_DIR="/www/wwwroot/chat.aigcqun.cn"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$PROJECT_DIR/app.pid"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 函数：打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 函数：检查进程是否运行
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# 函数：启动服务
start_service() {
    if is_running; then
        print_warn "服务已经在运行中 (PID: $(cat $PID_FILE))"
        return 1
    fi

    print_info "正在启动服务..."
    
    cd "$PROJECT_DIR" || exit 1

    # 检查 Neo4j 服务状态
    print_info "检查 Neo4j 服务..."
    if command -v neo4j &> /dev/null; then
        if command -v systemctl &> /dev/null && systemctl is-active --quiet neo4j 2>/dev/null; then
            print_info "Neo4j 运行中 ✓"
        elif pgrep -f "neo4j" > /dev/null 2>&1; then
            print_info "Neo4j 进程已存在 ✓"
        else
            print_warn "Neo4j 已安装但未运行，尝试启动..."
            systemctl start neo4j 2>/dev/null || neo4j start 2>/dev/null || true
            sleep 3
            if pgrep -f "neo4j" > /dev/null 2>&1; then
                print_info "Neo4j 启动成功 ✓"
            else
                print_warn "Neo4j 启动失败，GraphRAG 功能可能不可用"
                print_warn "手动启动: systemctl start neo4j"
            fi
        fi
    else
        print_warn "Neo4j 未安装，GraphRAG 功能将不可用"
        print_warn "初次部署请先运行: ./deploy.sh"
    fi

    # 启动前杀死所有占用相关端口的进程
    print_info "清理占用端口的进程..."
    pkill -f "python.*run.py" 2>/dev/null || true
    pkill -f "uvicorn" 2>/dev/null || true
    pkill -f "main:app" 2>/dev/null || true
    for PORT in 8000; do
        if fuser "$PORT/tcp" > /dev/null 2>&1; then
            print_warn "端口 $PORT 被占用，正在释放..."
            fuser -k "$PORT/tcp" > /dev/null 2>&1 || true
        fi
    done
    sleep 1
    print_info "端口清理完成"

    # 自动检查并安装依赖
    print_info "检查依赖并自动修复..."
    # 尝试安装 requirements.txt 中的依赖
    if [ -f "requirements.txt" ]; then
        python -m pip install -r requirements.txt || print_warn "依赖安装部分失败，尝试继续启动..."
    else
        print_warn "未找到 requirements.txt，跳过依赖安装"
    fi

    # 启动前自动同步数据库表结构和补列迁移
    print_info "同步数据库表结构..."
    python - <<'PYEOF'
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_backend"))

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
                print(f"  Migrated: {table}.{column} added.")
        except Exception as e:
            print(f"  Skip {table}.{column}: {e}")

async def main():
    from app.core.database import engine, Base
    import app.models  # noqa
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.begin() as conn:
            await conn.run_sync(_migrate_columns)
        print("  Database sync done.")
    except Exception as e:
        print(f"  Warning: {e}")
    finally:
        await engine.dispose()

asyncio.run(main())
PYEOF
    
    # 使用nohup后台启动
    nohup python llm_backend/run.py > "$LOG_DIR/app.log" 2>&1 &
    
    # 保存PID
    echo $! > "$PID_FILE"
    
    # 等待2秒检查是否启动成功
    sleep 2
    
    if is_running; then
        print_info "服务启动成功！"
        print_info "PID: $(cat $PID_FILE)"
        print_info "日志文件: $LOG_DIR/app.log"
        print_info "查看日志: tail -f $LOG_DIR/app.log"
        return 0
    else
        print_error "服务启动失败，请查看日志: $LOG_DIR/app.log"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 函数：停止服务
stop_service() {
    if ! is_running; then
        print_warn "服务未运行"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    print_info "正在停止服务 (PID: $PID)..."
    
    # 尝试优雅关闭
    kill "$PID" 2>/dev/null
    
    # 等待最多10秒
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            print_info "服务已停止"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    
    # 强制关闭
    print_warn "优雅关闭超时，强制停止..."
    kill -9 "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    print_info "服务已强制停止"
    return 0
}

# 函数：重启服务
restart_service() {
    print_info "正在重启服务..."
    stop_service
    sleep 2
    start_service
}

# 函数：查看服务状态
status_service() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        print_info "服务正在运行"
        print_info "PID: $PID"
        print_info "运行时间: $(ps -p $PID -o etime= | tr -d ' ')"
        print_info "内存使用: $(ps -p $PID -o rss= | awk '{printf "%.2f MB", $1/1024}')"
        print_info "CPU使用: $(ps -p $PID -o %cpu= | tr -d ' ')%"
    else
        print_warn "服务未运行"
        if [ -f "$PID_FILE" ]; then
            print_warn "发现残留PID文件，已清理"
            rm -f "$PID_FILE"
        fi
    fi
}

# 函数：查看日志
view_logs() {
    if [ -f "$LOG_DIR/app.log" ]; then
        print_info "实时查看日志 (Ctrl+C 退出)..."
        tail -f "$LOG_DIR/app.log"
    else
        print_error "日志文件不存在: $LOG_DIR/app.log"
    fi
}

# 函数：显示帮助信息
show_help() {
    echo "用法: $0 {start|stop|restart|status|logs|help}"
    echo ""
    echo "命令说明:"
    echo "  start   - 启动服务（后台运行）"
    echo "  stop    - 停止服务"
    echo "  restart - 重启服务"
    echo "  status  - 查看服务状态"
    echo "  logs    - 实时查看日志"
    echo "  help    - 显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 start          # 启动服务"
    echo "  $0 status         # 查看状态"
    echo "  $0 logs           # 查看日志"
    echo "  nohup $0 start &  # 后台启动（关闭终端也继续运行）"
}

# 主逻辑
case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        status_service
        ;;
    logs)
        view_logs
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "无效的命令: $1"
        echo ""
        show_help
        exit 1
        ;;
esac

exit 0
