# 使用 Python 3.11 镜像作为基础
FROM python:3.11-slim

# 设置北京时区 (UTC+8)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置环境变量，确保 Python 输出不被缓冲，方便在控制台查看实时日志
ENV PYTHONUNBUFFERED=1

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（如果有些库需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 1. 首先只复制依赖文件并安装 (最大化利用 Docker 缓存层)
# 只要 requirements.txt 没变，这一步在后续构建中会显示为 CACHED，完全跳过下载过程
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 最后才复制后端代码 (业务代码变动频繁，放在依赖安装之后)
COPY llm_backend/ ./

# 暴露后端端口（与 run.py 中配置一致）
EXPOSE 8000

# 启动命令
CMD ["python", "run.py"]
