# Personal AI Memory System (Project Chimera)

个人AI记忆核心 - 一个与您共生的、可进化的个人认知中枢。

## 🎯 项目愿景

打造一个与我共生的、可进化的个人认知中枢。它不仅是过去记忆的存储器，更是未来创造的加速器，让 AI 成为真正懂我、助我成长的"第二大脑"。

## 🏗 系统架构

### 核心设计原则

- **图谱即索引 (Graph as Index)**: Notion 是唯一的事实源头和内容载体；图数据库是其上的一层智能关系网络
- **不重复原则 (No Duplication)**: 严格遵守数据极简，图数据库不存储Notion页面正文，仅存储关系和元数据
- **用户无感 (Seamless Experience)**: 所有后台同步和索引工作对用户透明

### 双服务架构

1. **后台同步服务 (The Archivist - 档案保管员)**
   - 独立、低频运行的进程
   - 忠实地读取Notion，并使用Graphiti根据数据模型更新Neo4j图谱索引

2. **MCP检索服务 (The Navigator - 导航员)**
   - 轻量、快速、无状态的服务
   - 响应LLM的请求，在图谱中快速搜索，并返回notionId列表

## 🔧 技术栈

- **语言**: Python 3.11+
- **包管理**: UV
- **图数据库**: Neo4j
- **图操作**: Graphiti
- **内容源**: Notion API
- **嵌入模型**: Google Gemini
- **API协议**: MCP (Model Context Protocol)
- **数据验证**: Pydantic
- **日志**: Loguru

## 🚀 快速开始

### 1. 环境安装

```bash
# 克隆项目
git clone <your-repo-url>
cd personal-ai-memory

# 使用UV安装依赖
uv sync

# 复制环境配置
cp .env.example .env
```

### 2. 配置环境变量

编辑 `.env` 文件，配置以下关键信息：

```bash
# Neo4j 配置
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password_here

# Notion 配置
NOTION_TOKEN=your_notion_integration_token_here

# Gemini 配置
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. 初始化数据库

```bash
# 设置数据库约束和索引
python scripts/setup_database.py

# 验证数据库连接
python scripts/setup_database.py --test
```

### 4. 运行健康检查

```bash
# 全面健康检查
python scripts/health_check.py

# 检查特定组件
python scripts/health_check.py --check notion
python scripts/health_check.py --check neo4j
```

### 5. 启动服务

#### 同步服务 (The Archivist)
```bash
# 手动同步
python scripts/manual_sync.py

# 全量同步
python scripts/manual_sync.py --full

# 启动后台同步服务
python -m sync_service.main
```

#### MCP服务 (The Navigator)
```bash
# 启动MCP服务器
python -m mcp_server.server
```

## 🛠 核心功能

### MCP工具

#### 1. search(query, limit=10)
语义搜索您的Notion知识库
```json
{
    "query": "搜索查询",
    "limit": 10
}
```

#### 2. expand(page_ids, depth=1, relation_types=null)
从给定页面扩展找到相关页面
```json
{
    "page_ids": ["page-id-1", "page-id-2"],
    "depth": 2,
    "relation_types": ["LINKS_TO", "MENTIONS"]
}
```

#### 3. get_content(page_ids, include_metadata=true)
获取页面完整内容
```json
{
    "page_ids": ["page-id-1", "page-id-2"],
    "include_metadata": true
}
```

## 📊 核心查询工作流

1. **查询发起**: 用户向集成了本系统的AI应用提问
2. **关系导航**: MCP检索服务在图数据库中通过语义搜索和关系遍历找到相关页面
3. **返回ID列表**: MCP服务返回排序后的notionId列表
4. **内容获取**: AI应用通过Notion API实时获取页面原文
5. **上下文构建**: 组合"关系摘要"和"页面原文"
6. **生成回答**: LLM基于丰富上下文生成精准回答

## 🔄 同步机制

### 增量同步
- 基于 `last_edited_time` 检测变化
- 批量处理，避免API限制
- 智能重试机制

### 关系提取
- 自动检测 `[[内部链接]]`
- 解析 `@提及`
- 处理数据库关系属性
- 提取和聚类标签

## 📈 监控和维护

### 健康检查
```bash
# 全面检查
python scripts/health_check.py

# JSON格式输出
python scripts/health_check.py --json

# 特定检查
python scripts/health_check.py --check integrity
```

### 同步状态
```bash
# 查看同步统计
python scripts/manual_sync.py --stats

# 测试组件
python scripts/manual_sync.py --test
```

### 日志管理
- 日志文件: `logs/chimera.log`
- 错误日志: `logs/chimera_errors.log`
- 自动轮转和压缩
- JSON格式便于分析

## 🔍 故障排除

### 常见问题

1. **Neo4j连接失败**
   ```bash
   # 检查Neo4j服务状态
   python scripts/health_check.py --check neo4j
   
   # 验证配置
   python scripts/setup_database.py --test
   ```

2. **Notion API权限错误**
   ```bash
   # 检查API权限
   python scripts/health_check.py --check notion
   ```

3. **嵌入服务不可用**
   ```bash
   # 检查Gemini API
   python scripts/health_check.py --check embedding
   ```

## 🤝 开发指南

### 代码规范
- 使用 `black` 格式化代码
- 使用 `ruff` 进行代码检查
- 使用 `mypy` 进行类型检查

```bash
# 代码格式化
uv run black .

# 代码检查
uv run ruff check .

# 类型检查
uv run mypy .
```

### 测试
```bash
# 运行测试
uv run pytest

# 带覆盖率
uv run pytest --cov=.

# 运行完整测试套件
python scripts/run_tests.py
```

## 📝 版本历史

### v0.1.0 (当前版本)
- ✅ 完整的双服务架构
- ✅ Notion API集成
- ✅ Neo4j + Graphiti图操作
- ✅ Gemini嵌入服务
- ✅ MCP协议支持
- ✅ 自动同步机制
- ✅ 健康检查和监控

## 🎯 未来规划

- [ ] Web界面管理
- [ ] 更多LLM模型支持
- [ ] 高级分析和可视化
- [ ] 插件系统
- [ ] 多用户支持

## 📄 许可证

MIT License

## 🙏 致谢

- [Graphiti](https://github.com/getzep/graphiti) - 强大的图数据库操作框架
- [Notion API](https://developers.notion.com/) - 优秀的内容管理平台
- [Google Gemini](https://ai.google.dev/) - 高质量的嵌入模型

---

**Project Chimera** - 让AI真正理解您的知识，成为您思维的延伸。