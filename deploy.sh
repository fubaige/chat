#!/bin/bash
# 一键部署脚本

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  Chat AI 一键部署脚本"
echo "=========================================="
echo ""

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo "[WARN] 建议使用root用户运行此脚本"
fi

# 项目目录
PROJECT_DIR="/www/wwwroot/chat.aigcqun.cn"

echo "[1/8] 检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3未安装，请先安装Python3"
    exit 1
fi
python3 --version

echo ""
echo "[2/8] 检查pip..."
if ! command -v pip3 &> /dev/null; then
    echo "[ERROR] pip3未安装，请先安装pip3"
    exit 1
fi
pip3 --version

echo ""
echo "[3/8] 安装Python依赖..."
cd "$PROJECT_DIR"
pip3 install -r requirements.txt

echo ""
echo "[4/8] 检测并安装 Neo4j..."
install_neo4j() {
    echo "      Neo4j 未安装，开始自动安装..."

    # 检测系统类型
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        echo "      检测到 Debian/Ubuntu 系统"
        # 添加 Neo4j GPG key 和 apt 源
        if ! command -v curl &> /dev/null; then
            apt-get install -y curl
        fi
        curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key | gpg --dearmor -o /usr/share/keyrings/neo4j.gpg
        echo "deb [signed-by=/usr/share/keyrings/neo4j.gpg] https://debian.neo4j.com stable latest" \
            > /etc/apt/sources.list.d/neo4j.list
        apt-get update -qq
        # 安装 Java（Neo4j 依赖）
        if ! command -v java &> /dev/null; then
            echo "      安装 Java 运行环境..."
            apt-get install -y openjdk-17-jre-headless
        fi
        apt-get install -y neo4j
        echo "      Neo4j 安装完成（apt）"

    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        echo "      检测到 CentOS/RHEL 系统"
        rpm --import https://debian.neo4j.com/neotechnology.gpg.key
        cat > /etc/yum.repos.d/neo4j.repo << 'EOF'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
EOF
        # 安装 Java
        if ! command -v java &> /dev/null; then
            echo "      安装 Java 运行环境..."
            yum install -y java-17-openjdk-headless
        fi
        yum install -y neo4j
        echo "      Neo4j 安装完成（yum）"

    elif command -v dnf &> /dev/null; then
        # Fedora/newer RHEL
        echo "      检测到 Fedora/RHEL 系统"
        rpm --import https://debian.neo4j.com/neotechnology.gpg.key
        cat > /etc/yum.repos.d/neo4j.repo << 'EOF'
[neo4j]
name=Neo4j RPM Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
EOF
        if ! command -v java &> /dev/null; then
            dnf install -y java-17-openjdk-headless
        fi
        dnf install -y neo4j
        echo "      Neo4j 安装完成（dnf）"

    else
        echo "      [WARN] 无法识别包管理器，跳过自动安装 Neo4j"
        echo "      请手动安装 Neo4j: https://neo4j.com/docs/operations-manual/current/installation/"
        return 1
    fi
}

check_and_configure_neo4j() {
    if command -v neo4j &> /dev/null; then
        echo "      Neo4j 已安装: $(neo4j --version 2>/dev/null || echo '版本未知')"
    else
        install_neo4j || return 0  # 安装失败不中断整体部署
    fi

    # 配置 Neo4j 允许远程连接（默认只监听 localhost）
    NEO4J_CONF="/etc/neo4j/neo4j.conf"
    if [ -f "$NEO4J_CONF" ]; then
        # 开启 Bolt 监听
        if grep -q "^#server.bolt.listen_address" "$NEO4J_CONF"; then
            sed -i 's/^#server.bolt.listen_address.*/server.bolt.listen_address=0.0.0.0:7687/' "$NEO4J_CONF"
        elif ! grep -q "^server.bolt.listen_address" "$NEO4J_CONF"; then
            echo "server.bolt.listen_address=0.0.0.0:7687" >> "$NEO4J_CONF"
        fi
        echo "      Neo4j 配置已更新"
    fi

    # 启用并启动 Neo4j 服务
    if command -v systemctl &> /dev/null; then
        systemctl enable neo4j 2>/dev/null || true
        if ! systemctl is-active --quiet neo4j; then
            echo "      启动 Neo4j 服务..."
            systemctl start neo4j
            sleep 5
        fi
        if systemctl is-active --quiet neo4j; then
            echo "      Neo4j 服务运行中 ✓"
        else
            echo "      [WARN] Neo4j 服务启动失败，请手动检查: systemctl status neo4j"
        fi
    else
        echo "      [WARN] systemctl 不可用，请手动启动 Neo4j"
    fi
}

check_and_configure_neo4j

echo ""
echo "[5/8] 设置脚本权限..."
chmod +x start.sh
chmod +x deploy.sh

echo ""
echo "[6/8] 创建必要目录..."
mkdir -p logs
mkdir -p uploads
mkdir -p llm_backend/app/graphrag/data/input
mkdir -p llm_backend/app/graphrag/data/output

echo ""
echo "[7/8] 检查配置文件..."
if [ ! -f "llm_backend/.env" ]; then
    echo "[WARN] .env文件不存在"
    if [ -f "llm_backend/.env.example" ]; then
        echo "      正在从.env.example创建.env..."
        cp llm_backend/.env.example llm_backend/.env
        echo "      请编辑 llm_backend/.env 配置数据库等信息"
    fi
fi

echo ""
echo "[8/8] 检查 Neo4j Python 驱动..."
if ! python3 -c "import neo4j" &> /dev/null; then
    echo "      安装 neo4j Python 驱动..."
    pip3 install neo4j langchain-neo4j
else
    echo "      neo4j Python 驱动已安装 ✓"
fi

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "下一步操作："
echo "  1. 编辑配置文件: nano llm_backend/.env"
echo "     重要: 设置 NEO4J_PASSWORD 为你的 Neo4j 密码"
echo "  2. 启动服务: ./start.sh start"
echo "  3. 查看状态: ./start.sh status"
echo "  4. 查看日志: ./start.sh logs"
echo ""
echo "Neo4j 管理："
echo "  - 浏览器界面: http://localhost:7474"
echo "  - 默认账号: neo4j / neo4j (首次登录需修改密码)"
echo "  - 服务状态: systemctl status neo4j"
echo ""
echo "详细文档: cat DEPLOYMENT_GUIDE.md"
echo ""
