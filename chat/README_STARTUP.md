# 🚀 服务器启动快速指南

## 📋 一分钟快速启动

### Linux服务器（生产环境）

```bash
# 1. 进入项目目录
cd /www/wwwroot/chat.aigcqun.cn

# 2. 添加执行权限（首次）
chmod +x start.sh

# 3. 启动服务（后台运行）
./start.sh start

# 4. 查看状态
./start.sh status
```

**就这么简单！** 服务会在后台运行，关闭SSH终端也不会停止。

---

## 📚 完整命令列表

| 命令 | 说明 |
|------|------|
| `./start.sh start` | 启动服务（后台运行） |
| `./start.sh stop` | 停止服务 |
| `./start.sh restart` | 重启服务 |
| `./start.sh status` | 查看运行状态 |
| `./start.sh logs` | 实时查看日志 |
| `./start.sh help` | 显示帮助信息 |

---

## 🔍 检查服务是否运行

```bash
# 方法1：使用脚本（推荐）
./start.sh status

# 方法2：查看进程
ps aux | grep "python.*run.py"

# 方法3：测试API
curl http://localhost:7002/health
```

---

## 📝 查看日志

```bash
# 实时查看（推荐）
./start.sh logs

# 查看最近100行
tail -n 100 logs/app.log

# 查看错误
grep ERROR logs/app.log
```

---

## 🔧 常见问题

### Q: 如何确保关闭SSH后服务继续运行？

A: 使用 `./start.sh start` 即可，服务会自动在后台运行。

### Q: 如何更新代码？

```bash
./start.sh stop          # 停止服务
git pull                 # 更新代码
pip install -r requirements.txt  # 更新依赖
./start.sh start         # 启动服务
```

### Q: 端口被占用怎么办？

```bash
lsof -i :7002           # 查看占用进程
./start.sh stop         # 停止服务
```

### Q: 服务无法启动？

```bash
cat logs/app.log        # 查看错误日志
python llm_backend/run.py  # 手动运行查看错误
```

---

## 📁 文件说明

- `start.sh` - Linux启动脚本（生产环境）
- `start.bat` - Windows启动脚本（本地开发）
- `deploy.sh` - 一键部署脚本
- `logs/app.log` - 应用日志文件
- `app.pid` - 进程ID文件

---

## 📖 详细文档

- **完整部署指南**: `DEPLOYMENT_GUIDE.md`
- **服务器启动**: `SERVER_STARTUP.md`
- **微信集成**: `README_WECHAT.md`

---

## ⚡ 快速命令

```bash
# 启动
./start.sh start

# 查看状态
./start.sh status

# 查看日志
./start.sh logs

# 重启
./start.sh restart

# 停止
./start.sh stop
```

---

## 🎯 生产环境建议

1. ✅ 使用 `./start.sh start` 后台运行
2. ✅ 定期查看日志 `./start.sh logs`
3. ⚠️ 配置Nginx反向代理（参考DEPLOYMENT_GUIDE.md）
4. ⚠️ 启用HTTPS
5. ⚠️ 配置开机自启动
6. ⚠️ 定期备份数据库

---

## 💡 提示

- 日志文件位置: `logs/app.log`
- PID文件位置: `app.pid`
- 配置文件: `llm_backend/.env`
- 服务默认端口: `8000`

---

**需要帮助？** 运行 `./start.sh help` 查看更多信息
