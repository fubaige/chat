# 启动脚本功能总结

## 🎉 已创建的文件

### 1. **start.sh** - 主启动脚本（Linux生产环境）

**功能特性：**
- ✅ 后台运行（nohup）
- ✅ 进程管理（PID文件）
- ✅ 日志记录（logs/app.log）
- ✅ 优雅关闭（SIGTERM → SIGKILL）
- ✅ 状态监控（CPU、内存、运行时间）
- ✅ 彩色输出（易于阅读）
- ✅ 关闭SSH终端也继续运行

**支持命令：**
```bash
./start.sh start    # 启动服务
./start.sh stop     # 停止服务
./start.sh restart  # 重启服务
./start.sh status   # 查看状态
./start.sh logs     # 查看日志
./start.sh help     # 帮助信息
```

### 2. **start.bat** - Windows启动脚本

**用途：** 本地开发环境（Windows）

**功能：**
- 检查Python环境
- 启动开发服务器
- 控制台输出日志

### 3. **deploy.sh** - 一键部署脚本

**功能：**
- 检查Python环境
- 安装依赖包
- 设置文件权限
- 创建必要目录
- 检查配置文件

**使用：**
```bash
chmod +x deploy.sh
./deploy.sh
```

### 4. **文档文件**

- `DEPLOYMENT_GUIDE.md` - 完整部署和运维指南
- `SERVER_STARTUP.md` - 服务器启动详细说明
- `README_STARTUP.md` - 快速启动指南

---

## 🚀 使用流程

### 首次部署

```bash
# 1. 上传所有文件到服务器
cd /www/wwwroot/chat.aigcqun.cn

# 2. 添加执行权限
chmod +x start.sh deploy.sh

# 3. 运行部署脚本（可选）
./deploy.sh

# 4. 编辑配置文件
nano llm_backend/.env

# 5. 启动服务
./start.sh start

# 6. 检查状态
./start.sh status
```

### 日常使用

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

## 📊 脚本特性对比

| 特性 | start.sh | start.bat | deploy.sh |
|------|----------|-----------|-----------|
| 后台运行 | ✅ | ❌ | N/A |
| 进程管理 | ✅ | ❌ | N/A |
| 日志记录 | ✅ | ❌ | N/A |
| 状态监控 | ✅ | ❌ | N/A |
| 优雅关闭 | ✅ | ❌ | N/A |
| 环境检查 | ✅ | ✅ | ✅ |
| 依赖安装 | ❌ | ❌ | ✅ |
| 平台 | Linux | Windows | Linux |

---

## 🔧 技术实现

### start.sh 核心功能

1. **后台运行**
   ```bash
   nohup python llm_backend/run.py > "$LOG_DIR/app.log" 2>&1 &
   echo $! > "$PID_FILE"
   ```

2. **进程检查**
   ```bash
   if ps -p "$PID" > /dev/null 2>&1; then
       return 0  # 运行中
   fi
   ```

3. **优雅关闭**
   ```bash
   kill "$PID"           # 先尝试SIGTERM
   sleep 10              # 等待10秒
   kill -9 "$PID"        # 强制SIGKILL
   ```

4. **状态监控**
   ```bash
   ps -p $PID -o etime=  # 运行时间
   ps -p $PID -o rss=    # 内存使用
   ps -p $PID -o %cpu=   # CPU使用
   ```

---

## 📁 文件结构

```
/www/wwwroot/chat.aigcqun.cn/
├── start.sh                    # Linux启动脚本 ⭐
├── start.bat                   # Windows启动脚本
├── deploy.sh                   # 部署脚本
├── app.pid                     # 进程ID文件（自动生成）
├── logs/
│   └── app.log                # 应用日志（自动生成）
├── llm_backend/
│   ├── run.py                 # 主程序入口
│   └── .env                   # 配置文件
├── DEPLOYMENT_GUIDE.md        # 完整部署指南
├── SERVER_STARTUP.md          # 启动说明
└── README_STARTUP.md          # 快速指南
```

---

## ✅ 解决的问题

### 问题1：关闭SSH后服务停止
**解决方案：** 使用nohup后台运行
```bash
nohup python run.py > logs/app.log 2>&1 &
```

### 问题2：无法管理进程
**解决方案：** PID文件记录进程ID
```bash
echo $! > app.pid
```

### 问题3：日志难以查看
**解决方案：** 统一日志文件
```bash
./start.sh logs  # 实时查看
```

### 问题4：不知道服务状态
**解决方案：** 状态监控命令
```bash
./start.sh status  # 显示CPU、内存、运行时间
```

---

## 🎯 最佳实践

### 1. 生产环境启动

```bash
# 推荐方式
./start.sh start

# 验证
./start.sh status
./start.sh logs
```

### 2. 更新部署

```bash
./start.sh stop
git pull
pip install -r requirements.txt
./start.sh start
```

### 3. 故障排查

```bash
# 查看日志
./start.sh logs

# 查看状态
./start.sh status

# 手动运行
python llm_backend/run.py
```

### 4. 性能监控

```bash
# 使用脚本
./start.sh status

# 详细监控
top -p $(cat app.pid)
```

---

## 🔐 安全建议

1. ✅ 脚本已实现进程隔离
2. ✅ 日志文件权限控制
3. ⚠️ 建议使用非root用户运行
4. ⚠️ 建议配置防火墙
5. ⚠️ 建议使用Nginx反向代理
6. ⚠️ 建议启用HTTPS

---

## 📞 获取帮助

```bash
# 查看帮助
./start.sh help

# 查看文档
cat DEPLOYMENT_GUIDE.md
cat SERVER_STARTUP.md
cat README_STARTUP.md

# 查看日志
./start.sh logs
```

---

## 🎊 总结

现在你有了一套完整的生产环境启动方案：

1. ✅ **简单易用** - 一条命令启动服务
2. ✅ **后台运行** - 关闭SSH也继续运行
3. ✅ **进程管理** - 启动、停止、重启、状态
4. ✅ **日志记录** - 统一日志文件
5. ✅ **状态监控** - CPU、内存、运行时间
6. ✅ **完整文档** - 详细的使用说明

**立即开始使用：**
```bash
chmod +x start.sh
./start.sh start
./start.sh status
```

🎉 **享受自动化部署的便利！**
