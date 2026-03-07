@echo off
REM Windows环境启动脚本（用于本地开发）

echo ========================================
echo   Chat AI 服务启动脚本 (Windows)
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python未安装或未添加到PATH
    pause
    exit /b 1
)

echo [INFO] 正在检查并安装缺失依赖...
python -m pip install -r requirements.txt

echo [INFO] 正在启动服务...
echo [INFO] 日志将输出到控制台
echo [INFO] 按 Ctrl+C 停止服务
echo.

cd llm_backend
python run.py

pause
