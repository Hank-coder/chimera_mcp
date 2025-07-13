# Project Chimera

🧠 **个人AI记忆系统** - 让AI成为真正懂你的"第二大脑"

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![UV](https://img.shields.io/badge/uv-latest-green.svg)](https://github.com/astral-sh/uv)
[![Neo4j](https://img.shields.io/badge/neo4j-5.x-red.svg)](https://neo4j.com/)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)

## ✨ 特性

- 🔗 **智能关系图谱**: 自动构建Notion页面间的语义关系网络
- 🚀 **MCP协议支持**: 与Claude Desktop等AI客户端无缝集成
- 🔍 **意图搜索**: 基于自然语言理解的智能内容检索
- ⚡ **实时同步**: 自动监测Notion变更并增量更新图谱
- 🛡️ **数据安全**: 图数据库仅存储关系和元数据，内容从Notion实时获取

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Neo4j 数据库
- Notion API Token
- Google Gemini API Key

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-username/Chimera.git
cd Chimera

# 使用 uv 安装依赖（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 配置

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的配置：
```bash
# Neo4j 配置
NEO4J_URI=neo4j://your-neo4j-server:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password

# Notion API
NOTION_TOKEN=your_notion_integration_token

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key

# MCP 服务器
CHIMERA_API_KEY=your_api_key
```

### 使用方法

#### 启动服务 具体见 server_config.md

```bash
# 启动 MCP 服务器
uv run fastmcp_server.py --host 0.0.0.0 --port 3000

# 启动同步服务
uv run run_chimera.py
```

#### 后台运行

```bash
# 后台启动服务
nohup uv run fastmcp_server.py --host 0.0.0.0 --port 3000 > mcp_server.log 2>&1 &
nohup uv run run_chimera.py > sync_service.log 2>&1 &

# 检查状态
ps aux | grep fastmcp_server
ps aux | grep run_chimera

# 停止服务
pkill -f fastmcp_server
pkill -f run_chimera
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
        "http://your-server:3000/mcp/",
        "--header",
        "Authorization:Bearer your_api_key",
        "--allow-http"
      ]
    }
  }
}
```

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

1. **数据同步**: 监控Notion变更并提取页面关系
2. **图谱构建**: 在Neo4j中创建带嵌入向量的语义图谱
3. **意图搜索**: 处理自然语言查询，找到相关内容
4. **MCP接口**: 通过Model Context Protocol为AI客户端提供服务

## 🤝 贡献

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交你的修改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开一个 Pull Request

## 📝 文档

- [服务器配置指南](server_config.md) - 完整的部署配置
- [开发指南](docs/DEVELOPMENT_GUIDE.md) - 详细的开发说明

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [Graphiti](https://github.com/getzep/graphiti) - 图数据库操作框架
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP服务器框架
- [Notion API](https://developers.notion.com/) - 内容管理平台
- [Google Gemini](https://ai.google.dev/) - LLM模型

---

⭐ **如果这个项目对你有帮助，请给个Star！**