# Project Chimera

🧠 **个人AI记忆系统** - 让AI成为真正懂你的"第二大脑"

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![UV](https://img.shields.io/badge/uv-latest-green.svg)](https://github.com/astral-sh/uv)
[![Neo4j](https://img.shields.io/badge/neo4j-5.x-red.svg)](https://neo4j.com/)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)

## ✨ 特性

- 🔗 **智能关系图谱**: 自动构建Notion页面间的语义关系网络
- 🚀 **MCP协议支持**: 与Claude Desktop等AI客户端无缝集成，支持多客户端并发访问
- 🔍 **意图搜索**: 基于自然语言理解的智能Notion内容检索，支持文本和PDF/EXCEL/WORD文档
- ⚡ **智能同步**: 增量同步(30分钟) + 全量同步(隔天凌晨4点或超过3天)
- 🛡️ **数据安全**: 图数据库仅存储关系和元数据，内容从Notion实时获取
- 📁 **文件支持**: 支持多种文件格式的内容提取和搜索（图片暂不支持）

## 🚀 快速开始（冷启动指南）

### 环境要求

- Python 3.11+
- Neo4j 5.0+ 数据库
- UV 包管理器
- Notion API Token
- Google Gemini API Key

### 一键安装

```bash
# 1. 克隆仓库
git clone <repo-url>
cd Chimera

# 2. 安装UV（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 使用 uv 安装依赖（推荐）
uv sync

# 4. 或使用 pip
pip install -r requirements.txt
```

### 配置设置

1. 创建环境配置：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的配置：
```bash
# Neo4j 配置
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password

# Notion API
NOTION_TOKEN=your_notion_integration_token

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key

# MCP 服务器
CHIMERA_API_KEY=your_api_key
```

3. 启动Neo4j数据库：
```bash
# 使用Docker启动（推荐）
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5.15

# 或使用本地安装的Neo4j
neo4j start
```

### 使用方法

#### 一键启动（推荐）

```bash
# 启动完整系统（包括同步服务和MCP服务器）
uv run python run_chimera.py
```

#### 分开启动（高级用法）

```bash
# 终端1: 启动 MCP 服务器
uv run python fastmcp_server.py --host 0.0.0.0 --port 3000

# 终端2: 启动同步服务
uv run python sync_service/sync_service.py
```

#### 生产环境部署

```bash
# 后台启动服务
nohup uv run python fastmcp_server.py --host 0.0.0.0 --port 3000 > logs/mcp_server.log 2>&1 &
nohup uv run python sync_service/sync_service.py > logs/sync_service.log 2>&1 &

# 检查服务状态
ps aux | grep fastmcp_server
ps aux | grep sync_service

# 停止服务
pkill -f fastmcp_server
pkill -f sync_service
```

#### Claude Desktop 集成

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "chimera-memory": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:3000/mcp/",
        "--header",
        "Authorization:Bearer your_api_key",
        "--allow-http"
      ]
    }
  }
}
```

更多集成详情参考：[server_config.md](server_config.md)

## 📁 项目结构

```
Chimera/
├── config/           # 配置管理
├── core/            # 核心业务逻辑和数据模型
├── sync_service/    # 后台同步服务
├── agents/          # 意图搜索和AI代理
├── prompts/         # LLM提示词模板
├── utils/           # 工具函数
├── scripts/         # 部署和维护脚本
└── tests/           # 测试套件
```

## 🔧 配置说明

主要环境变量：

| 变量名 | 描述 | 默认值 |
|--------|------|--------|
| `SYNC_INTERVAL_MINUTES` | 同步频率（分钟） | 30 |
| `NEO4J_URI` | Neo4j连接字符串 | neo4j://127.0.0.1:7687 |
| `NOTION_TOKEN` | Notion API令牌 | 必填 |
| `GEMINI_API_KEY` | Google Gemini API密钥 | 必填 |
| `MCP_SERVER_PORT` | MCP服务器端口 | 3000 |

## 📊 工作原理

### 核心流程
1. **数据同步**: 监控Notion变更并提取页面关系
2. **图谱构建**: 在Neo4j中创建带嵌入向量的语义图谱
3. **意图搜索**: 处理自然语言查询，找到相关内容
4. **MCP接口**: 通过Model Context Protocol为AI客户端提供服务

### 同步策略
- **增量同步**: 默认30分钟间隔，检测变化后更新
- **全量同步**: 隔天北京时间4:00-4:30自动执行，或超过3天强制执行
- **删除检测**: 全量同步时会清理Notion中已删除的页面

### 多客户端支持
- ✅ 多客户端同时连接：支持多个Claude Desktop实例同时连接
- ✅ 并发处理请求：可以同时处理最多10个搜索请求
- ✅ 无状态设计：每个请求独立处理，不互相影响
- ✅ Bearer认证：每个客户端可以使用相同的API Key


## 🤝 贡献

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交你的修改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开一个 Pull Request

## 📝 文档

- [服务器配置指南](server_config.md) - 完整的部署配置
- [开发指南](docs/DEVELOPMENT_GUIDE.md) - 详细的开发说明
- [CLAUDE.md](CLAUDE.md) - 项目架构和产品设计文档

## ⚠️ 常见问题

### 安装问题
- **UV安装失败**: 检查网络连接，或使用pip安装
- **Neo4j连接失败**: 检查端口是否占用，默认端口为7687
- **环境变量问题**: 确保.env文件在根目录下且格式正确

### 运行问题
- **同步失败**: 检查Notion Token是否有效且权限充足
- **搜索无结果**: 等待首次全量同步完成
- **MCP连接失败**: 检查端口和API Key配置

### 性能问题
- **同步过慢**: 调整`SYNC_INTERVAL_MINUTES`或检查Neo4j性能
- **内存占用过高**: 调整`SYNC_BATCH_SIZE`参数

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [Graphiti](https://github.com/getzep/graphiti) - 图数据库操作框架
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP服务器框架
- [Notion API](https://developers.notion.com/) - 内容管理平台
- [Google Gemini](https://ai.google.dev/) - LLM模型

---

⭐ **如果这个项目对你有帮助，请给个Star！**