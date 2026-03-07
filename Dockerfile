# 使用 Python 3.11 镜像作为基础
FROM python:3.11-slim

# 设置北京时区 (UTC+8)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（如果有些库需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY llm_backend/ ./

# 暴露后端端口（与 run.py 中配置一致）
EXPOSE 8000

# 启动命令
CMD ["python", "run.py"]
