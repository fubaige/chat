# Ai聊天客服+知识库+公众号/服务号自动回复 一键部署与使用文档
<img src="https://wecom-ai.oss-cn-beijing.aliyuncs.com/github/1.png" style="max-width: 100%; height: auto;">
<img src="https://wecom-ai.oss-cn-beijing.aliyuncs.com/github/2.png" style="max-width: 100%; height: auto;">
<img src="https://wecom-ai.oss-cn-beijing.aliyuncs.com/github/3.png" style="max-width: 100%; height: auto;">
## 项目介绍
智能客服和对话 AI 系统后端架构，提供完善的会话与大模型交互能力。支持 Docker 化部署，提供统一的一键执行脚本，并兼容云端虚拟主机的快速上线。

### 核心功能与特性
1. **多模型智能对话整合**
   - 接入多模态及领先的大语言模型，具备出色的意图识别、智能回复和指令遵从能力。
   - 包含防止对话幻觉（Hallucination）检测的优化机制及去重策略。
2. **知识库增强（RAG / GraphRAG）**
   - 内置强大的图数据库体系（Neo4j 集成），支持跨文档和实体的关系网络构建，从而进行基于知识图谱的深度检索与答疑（GraphRAG）。
3. **微信生态深度整合** (`wx-mp-svr-main`)
   - 提供了对微信公众号、服务号自动回复业务体系（如消息接收、事件钩子对接、AI 回复下行）的相关代码保留，随时可激活成为微信官方客服背后的超级大脑。
4. **稳定且具扩展性的系统底座**
   - 架构基于高效的 Python 框架，并引入了 Redis 进行缓存/消息队列分发，以 MySQL 支撑强大的基础业务数据。
   - 保障了并发服务状态下的极高稳定性和弹性延展能力。
5. **知识库文本块提取核心引擎加固** (2026-03-08):
   - 【底层清洗】二次加固 `storage.py`：针对 Parquet 写入过程中常见的 `ArrowInvalid` 错误（由混合列表类型引起），引入了严格的 `list[str]` 类型约束网关。
   - 【容错机制】将 `entity_ids`, `relationship_ids`, `text_unit_ids` 等关键列强制规范化为列表格式，消灭了由于单字符串或空值导致的类型推断冲突。
   - 【路径与直读】修复了 Docker 容器内的路径对齐问题，并启用了基于 `record_id` 隔离的文档全量直读检索。
   - 增加了索引构建时的详细调试日志输出。
6. **极简运维与持续集成**
   - 全面支持跨平台一键部署（涵盖本地直接挂卷启动及云端容器化），并提供用于快速发布并重建 Docker 环境的自动化脚本（集成从代码提交、资源打包到自动远程激活的全环节）。

---

## 二、 服务器基础环境部署指南
**目标服务器信息：**
- **IP 地址**: ip地址
- **SSH 端口**: 59582
- **用户名**: root
- **项目路径**: `/www/wwwroot/chat.aigcqun.cn`
- **线上访问**: `http://ip地址:8000` (或绑定的域名)
- **核心服务映射端口**:
  - API 服务: `8000`
  - MySQL 数据库: `3307` (避开宿主机 3306 冲突)
  - Redis 缓存: `6381` (避开宿主机 6379 冲突)
  - Neo4j HTTP: `7474`, Bolt: `7687`

### 1. SSH 连接服务器
通过项目根目录下的 `.ssh_deploy_key` 密钥文件安全连接：
```bash
# 修改密钥权限（仅 Linux/Mac 适用，Windows 需通过属性设置）
chmod 400 .ssh_deploy_key

# 远程连接服务器
ssh -i .ssh_deploy_key -p 59582 root@IP地址
```

### 2. 获取代码与部署 (GitHub 方式)
在本地使用 Git 将代码推送到 GitHub（请先关联你的仓库地址），然后在服务器端拉取：
```bash
# 进入项目目录一键推送拉取部署
git add -A; git status --short
.\deploy-quick.ps1 -Message "fix: force Docker rebuild with BUILD_TIMESTAMP"


---

## 三、 Docker 部署指南 (推荐)
通过 `docker-compose`，你可以一键启动所有相关服务（后端服务、MySQL、Redis、Neo4j）。

1. 确认已在服务器 `/www/wwwroot/云空间目录` 目录下。
2. 确保已编写并在 `llm_backend/.env` 配置好对应账号密码等隐私数据（可参考 `.env.example`）。
3. 启动所有容器：
```bash
docker-compose up -d --build
```
4. **查看实时调试日志（重要）**：
```bash
# 查看后端日志
docker-compose logs -f backend
```

---

## 四、 本地脚本直接部署指南 (备选)
如果你不使用 Docker，也可以依靠提供的一键脚本在本地裸机/当前系统下运行。
1. **安装环境**：
```bash
bash deploy.sh
```
该脚本将检查 Python 环境并自动安装依赖、Neo4j 图数据库。

2. **生产环境后台运行**：
```bash
bash 生产.sh start
```
支持指令：`start` (启动)、`stop` (停止)、`restart` (重启)、`status` (查看状态)、`logs` (实时查看日志)。

3. **开发环境前台运行**：
```bash
bash 开发.sh
```
将清理占用端口并尝试修复依赖，并实时输出后端调试日志。

---
**提示：** 每次新增功能或修改核心逻辑后，请持续在此文档进行补充更新。
