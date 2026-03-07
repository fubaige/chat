# Python 智能体配置 Dockerfile
# 优化：分离依赖层和源码层，只缓存依赖安装

FROM python:3.11-slim

# 设置北京时区 (UTC+8)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置工作目录
WORKDIR /app

# 安装系统依赖，安装完立即清理 apt 缓存（这层会被缓存）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements.txt 并安装依赖（这层会被缓存，除非 requirements.txt 变化）
COPY requirements.txt .
# 加大超时时间 + 失败重试，避免网络抖动导致构建失败
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    --timeout 120 \
    --retries 5 \
    -r requirements.txt \
    && pip cache purge

# 复制后端代码（源码变化会使这层及之后的层缓存失效）
COPY llm_backend/ ./

# 清理 Python 缓存（减小镜像体积）
RUN find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true \
    && find . -name "*.pyc" -delete 2>/dev/null || true

# 暴露后端端口
EXPOSE 7002

# 启动命令
CMD ["python", "run.py"]
