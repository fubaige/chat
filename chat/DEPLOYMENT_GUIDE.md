# 生产环境部署指南

## 服务器启动脚本使用说明

### Linux服务器（生产环境）

#### 1. 上传并设置权限

```bash
# 上传start.sh到服务器
cd /www/wwwroot/chat.aigcqun.cn

# 添加执行权限
chmod +x start.sh
```

#### 2. 使用方法

```bash
# 启动服务（后台运行）
./start.sh start

# 查看服务状态
./start.sh status

# 停止服务
./start.sh stop

# 重启服务
./start.sh restart

# 实时查看日志
./start.sh logs

# 查看帮助
./start.sh help
```

#### 3. 后台运行（关闭终端也继续运行）

方法一：使用脚本自带的后台功能
```bash
./start.sh start
# 服务会自动在后台运行，可以直接关闭终端
```

方法二：使用nohup（双重保险）
```bash
nohup ./start.sh start > /dev/null 2>&1 &
```

#### 4. 查看运行状态

```bash
# 方法1：使用脚本
./start.sh status

# 方法2：手动查看进程
ps aux | grep "python.*run.py"

# 方法3：查看PID文件
cat app.pid
```

#### 5. 查看日志

```bash
# 实时查看（推荐）
./start.sh logs

# 或者直接查看日志文件
tail -f logs/app.log

# 查看最近100行
tail -n 100 logs/app.log

# 查看错误日志
grep ERROR logs/app.log
```

#### 6. 开机自启动（可选）

创建systemd服务：

```bash
sudo nano /etc/systemd/system/chat-ai.service
```

内容：
```ini
[Unit]
Description=Chat AI Service
After=network.target

[Service]
Type=forking
User=root
WorkingDirectory=/www/wwwroot/chat.aigcqun.cn
ExecStart=/www/wwwroot/chat.aigcqun.cn/start.sh start
ExecStop=/www/wwwroot/chat.aigcqun.cn/start.sh stop
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable chat-ai
sudo systemctl start chat-ai
sudo systemctl status chat-ai
```

### Windows环境（本地开发）

#### 使用start.bat

```cmd
# 双击运行start.bat
# 或在命令行中执行
start.bat
```

#### 后台运行（Windows）

```cmd
# 使用start命令在新窗口运行
start /B python llm_backend\run.py

# 或创建Windows服务（需要管理员权限）
# 推荐使用NSSM工具：https://nssm.cc/
```

## 常见问题

### 1. 端口被占用

```bash
# 查看端口占用
lsof -i :8000
netstat -tulpn | grep 8000

# 杀死占用进程
kill -9 <PID>
```

### 2. 权限问题

```bash
# 确保脚本有执行权限
chmod +x start.sh

# 确保日志目录可写
chmod 755 logs
```

### 3. Python环境问题

```bash
# 检查Python版本
python --version

# 检查依赖
pip list | grep fastapi

# 重新安装依赖
pip install -r requirements.txt
```

### 4. 服务无法启动

```bash
# 查看详细日志
cat logs/app.log

# 手动运行查看错误
cd /www/wwwroot/chat.aigcqun.cn
python llm_backend/run.py
```

### 5. 内存不足

```bash
# 查看内存使用
free -h

# 查看进程内存
ps aux --sort=-%mem | head

# 重启服务释放内存
./start.sh restart
```

## 监控和维护

### 1. 日志轮转（防止日志文件过大）

创建logrotate配置：
```bash
sudo nano /etc/logrotate.d/chat-ai
```

内容：
```
/www/wwwroot/chat.aigcqun.cn/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

### 2. 定时健康检查

添加到crontab：
```bash
crontab -e
```

添加：
```
*/5 * * * * /www/wwwroot/chat.aigcqun.cn/start.sh status > /dev/null 2>&1 || /www/wwwroot/chat.aigcqun.cn/start.sh start
```

### 3. 性能监控

```bash
# CPU和内存使用
./start.sh status

# 详细进程信息
top -p $(cat app.pid)

# 网络连接
netstat -anp | grep $(cat app.pid)
```

## 更新部署

```bash
# 1. 备份当前版本
cp -r /www/wwwroot/chat.aigcqun.cn /www/wwwroot/chat.aigcqun.cn.backup

# 2. 停止服务
./start.sh stop

# 3. 更新代码
git pull
# 或上传新文件

# 4. 更新依赖
pip install -r requirements.txt

# 5. 启动服务
./start.sh start

# 6. 检查状态
./start.sh status
./start.sh logs
```

## 安全建议

1. **使用非root用户运行**（如果可能）
2. **配置防火墙**，只开放必要端口
3. **使用HTTPS**（配置Nginx反向代理）
4. **定期备份数据库**
5. **监控日志中的异常访问**
6. **定期更新依赖包**

## Nginx反向代理配置（推荐）

```nginx
server {
    listen 80;
    server_name chat.aigcqun.cn;
    
    # 重定向到HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name chat.aigcqun.cn;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # 静态文件
    location /static {
        alias /www/wwwroot/chat.aigcqun.cn/llm_backend/static;
        expires 30d;
    }
    
    # API和WebSocket
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

## 快速命令参考

```bash
# 启动
./start.sh start

# 停止
./start.sh stop

# 重启
./start.sh restart

# 状态
./start.sh status

# 日志
./start.sh logs

# 后台启动（关闭终端也运行）
nohup ./start.sh start > /dev/null 2>&1 &
```
