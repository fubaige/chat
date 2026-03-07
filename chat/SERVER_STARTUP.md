# 服务器启动指南

## 快速开始

### 在Linux服务器上部署

```bash
# 1. 进入项目目录
cd /www/wwwroot/chat.aigcqun.cn

# 2. 给脚本添加执行权限（首次需要）
chmod +x start.sh deploy.sh

# 3. 一键部署（首次部署）
./deploy.sh

# 4. 启动服务（后台运行）
./start.sh start

# 5. 查看状态
./start.sh status
```

## 常用命令

### 服务管理

```bash
# 启动服务
./start.sh start

# 停止服务
./start.sh stop

# 重启服务
./start.sh restart

# 查看状态
./start.sh status

# 查看日志
./start.sh logs
```

### 后台运行（关闭SSH也继续运行）

```bash
# 方法1：直接使用start.sh（推荐）
./start.sh start
# 服务会自动在后台运行，可以直接关闭终端

# 方法2：使用nohup（双重保险）
nohup ./start.sh start > /dev/null 2>&1 &

# 方法3：使用screen（可以随时重新连接）
screen -S chat-ai
./start.sh start
# 按 Ctrl+A 然后按 D 离开screen
# 重新连接: screen -r chat-ai
```

## 文件说明

| 文件 | 说明 | 用途 |
|------|------|------|
| `start.sh` | Linux启动脚本 | 生产环境服务管理 |
| `start.bat` | Windows启动脚本 | 本地开发使用 |
| `deploy.sh` | 一键部署脚本 | 首次部署环境配置 |
| `DEPLOYMENT_GUIDE.md` | 详细部署文档 | 完整的部署和运维指南 |
| `app.pid` | 进程ID文件 | 记录服务进程ID |
| `logs/app.log` | 应用日志 | 服务运行日志 |

## 检查服务是否运行

```bash
# 方法1：使用脚本
./start.sh status

# 方法2：查看进程
ps aux | grep "python.*run.py"

# 方法3：查看PID文件
cat app.pid

# 方法4：测试API
curl http://localhost:7002/health
```

## 查看日志

```bash
# 实时查看（推荐）
./start.sh logs

# 查看最近100行
tail -n 100 logs/app.log

# 查看错误日志
grep ERROR logs/app.log

# 查看今天的日志
grep "$(date +%Y-%m-%d)" logs/app.log
```

## 故障排查

### 服务无法启动

```bash
# 1. 查看详细日志
cat logs/app.log

# 2. 手动运行查看错误
cd /www/wwwroot/chat.aigcqun.cn
python llm_backend/run.py

# 3. 检查端口占用
lsof -i :7002
netstat -tulpn | grep 8000

# 4. 检查Python环境
python --version
pip list | grep fastapi
```

### 端口被占用

```bash
# 查找占用进程
lsof -i :7002

# 杀死进程
kill -9 <PID>

# 或使用脚本停止
./start.sh stop
```

### 权限问题

```bash
# 添加执行权限
chmod +x start.sh

# 确保日志目录可写
chmod 755 logs
```

## 更新代码

```bash
# 1. 停止服务
./start.sh stop

# 2. 备份（可选）
cp -r /www/wwwroot/chat.aigcqun.cn /www/wwwroot/chat.aigcqun.cn.backup

# 3. 更新代码
git pull
# 或上传新文件

# 4. 更新依赖
pip install -r requirements.txt

# 5. 启动服务
./start.sh start

# 6. 检查状态
./start.sh status
```

## 性能监控

```bash
# 查看服务状态（包含CPU、内存）
./start.sh status

# 详细进程信息
top -p $(cat app.pid)

# 内存使用
free -h

# 磁盘使用
df -h
```

## 开机自启动

### 方法1：使用crontab

```bash
crontab -e
```

添加：
```
@reboot /www/wwwroot/chat.aigcqun.cn/start.sh start
```

### 方法2：使用systemd（推荐）

参考 `DEPLOYMENT_GUIDE.md` 中的systemd配置

## 安全建议

1. ✅ 使用start.sh后台运行（已支持）
2. ✅ 日志自动记录到文件（已配置）
3. ⚠️ 建议配置Nginx反向代理
4. ⚠️ 建议启用HTTPS
5. ⚠️ 建议配置防火墙
6. ⚠️ 定期备份数据库

## 快速命令速查表

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

# 帮助
./start.sh help
```

## 需要帮助？

- 详细文档: `cat DEPLOYMENT_GUIDE.md`
- 查看日志: `./start.sh logs`
- 检查状态: `./start.sh status`
- 手动运行: `python llm_backend/run.py`
