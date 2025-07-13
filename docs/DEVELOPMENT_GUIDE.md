# Chimera 项目开发文档

## 项目概览

Chimera 是一个个人AI记忆核心系统，旨在打造与用户共生的、可进化的个人认知中枢。本系统采用"图谱即索引"的核心哲学，以 Notion 为唯一事实源头，通过图数据库构建智能关系网络。

## 项目架构

### 核心设计原则
- **图谱即索引**: Neo4j 图数据库作为智能索引层，Notion 为内容载体
- **不重复原则**: 严格避免数据重复，图数据库仅存储关系和元数据
- **用户无感**: 所有后台处理对用户透明

### 双服务架构
1. **The Archivist (档案保管员)** - 后台同步服务
2. **The Navigator (导航员)** - MCP检索服务

## 目录结构与文件功能

### 根目录文件
- `run_chimera.py` - **主启动脚本**：提供命令行接口启动和管理整个系统
- `pyproject.toml` - 项目配置和依赖管理
- `requirements.txt` - Python 依赖列表
- `README.md` - 项目说明文档
- `CLAUDE.md` - 项目指令和规范

### config/ - 配置管理
- `settings.py` - **环境变量和配置管理**：统一管理所有系统配置
- `logging.py` - **日志配置**：统一的日志记录设置

### core/ - 核心业务逻辑
- `__init__.py` - 模块初始化
- `models.py` - **数据模型定义**：定义所有 Pydantic 数据模型
- `notion_client.py` - **Notion API客户端**：处理与 Notion 的所有交互
- `graphiti_client.py` - **Graphiti封装客户端**：管理图数据库操作

### sync_service/ - 后台同步服务 (The Archivist)
- `__init__.py` - 模块初始化
- `main.py` - **同步服务主入口**：协调整个同步流程
- `notion_scanner.py` - **Notion结构扫描器**：扫描 Notion 变更
- `graph_updater.py` - **图数据库更新器**：更新图谱结构
- `scheduler.py` - **定时任务调度器**：管理同步任务调度

### mcp_server/ - MCP检索服务 (The Navigator)
- `__init__.py` - 模块初始化
- `server.py` - **MCP服务器主体**：MCP协议服务器实现
- `concurrent_handler.py` - **并发处理器**：处理并发请求

#### mcp_server/tools/ - MCP工具集
- `__init__.py` - 模块初始化
- `search_tools.py` - **搜索工具**：语义搜索功能
- `navigation_tools.py` - **导航工具**：图关系遍历
- `context_tools.py` - **上下文工具**：内容获取功能

#### mcp_server/retrieval/ - 检索策略
- `__init__.py` - 模块初始化
- (待开发) `graph_retriever.py` - 图数据库检索
- (待开发) `notion_retriever.py` - Notion内容检索  
- (待开发) `hybrid_retriever.py` - 混合检索策略

### utils/ - 工具函数
- `__init__.py` - 模块初始化
- `daemon_manager.py` - **服务协调管理器**：协调两个核心服务的运行
- `embedding_utils.py` - **向量嵌入工具**：处理文本向量化

### scripts/ - 脚本工具
- `__init__.py` - 模块初始化
- `setup_database.py` - **数据库初始化**：设置 Neo4j 数据库
- `manual_sync.py` - **手动同步脚本**：触发一次性同步
- `health_check.py` - **健康检查**：系统状态检查
- `deployment_check.py` - **部署检查**：部署前验证
- `functional_test.py` - **功能测试**：全面功能测试
- `run_tests.py` - **测试运行器**：统一测试入口

### tests/ - 测试代码
- `__init__.py` - 模块初始化
- `notion/__init__.py` - Notion 相关测试
- `mcp_server/__init__.py` - MCP 服务器测试
- `sync_service/__init__.py` - 同步服务测试
- `utils/__init__.py` - 工具函数测试

### agents/ - LangGraph Agent (可选)
- `__init__.py` - 模块初始化
- (待开发) 智能Agent组件

### logs/ - 日志文件
- `chimera.log` - 系统运行日志
- `chimera_errors.log` - 错误日志

## 核心功能说明

### 1. 数据模型 (core/models.py)

#### 统一节点模型：NotionPageMetadata
- `notion_id`: Notion API的唯一标识符
- `title`: 页面标题，用于识别和基础搜索
- `type`: 对象类型 (page, database, block)
- `tags`: 页面标签，用于主题聚类
- `embedding`: AI生成的向量嵌入，用于语义搜索
- `last_edited_time`: 最后编辑时间，用于增量同步
- `url`: 直接链接到 Notion 页面

#### 五种核心关系类型
- `CHILD_OF`: 页面层级关系
- `LINKS_TO`: 内链关系 [[...]]
- `RELATED_TO`: 数据库关联关系
- `MENTIONS`: @提及关系
- `HAS_TAG`: 标签关系

### 2. 同步服务工作流

1. **健康检查**: 验证 Notion API 和 Neo4j 连接
2. **变更扫描**: 基于 `last_edited_time` 扫描变更
3. **关系提取**: 提取五种核心关系
4. **图谱更新**: 更新 Neo4j 图数据库
5. **状态记录**: 记录同步状态和统计信息

### 3. MCP服务器工具

#### search(query, limit)
- 语义搜索 Notion 知识库
- 返回相关页面ID列表，按相关性排序

#### expand(page_ids, depth, relation_types)
- 从给定页面ID出发扩展关系
- 遍历指定类型的关系网络

#### get_content(page_ids, include_metadata)
- 通过 Notion API 获取页面完整内容
- 可选包含元数据信息

## 开发流程

### 环境设置
1. 确保 Python 3.11+ 环境
2. 安装 UV 包管理器
3. 复制 `.env.example` 到 `.env` 并配置
4. 启动 Neo4j 数据库

### 开发命令
```bash
# 安装依赖
uv sync

# 运行完整系统
python run_chimera.py

# 仅运行同步服务
python run_chimera.py --sync-only

# 仅运行MCP服务
python run_chimera.py --mcp-only

# 手动同步
python run_chimera.py --manual-sync

# 系统状态检查
python run_chimera.py --status

# 部署前检查
python scripts/deployment_check.py

# 功能测试
python scripts/functional_test.py

# 健康检查
python scripts/health_check.py
```

### 测试策略
- **单元测试**: 测试独立功能模块
- **集成测试**: 测试服务间交互
- **功能测试**: 测试完整工作流
- **健康检查**: 监控系统状态

## 关键技术栈

- **图数据库**: Neo4j + Graphiti
- **内容源**: Notion API
- **向量嵌入**: Google Gemini API  
- **API协议**: MCP (Model Context Protocol)
- **数据验证**: Pydantic
- **日志系统**: Loguru
- **包管理**: UV
- **异步框架**: AsyncIO

## 扩展指南

### 添加新的关系类型
1. 在 `core/models.py` 中添加新的 `RelationType`
2. 在 `sync_service/notion_scanner.py` 中添加关系提取逻辑
3. 在 `sync_service/graph_updater.py` 中添加图更新逻辑

### 添加新的MCP工具
1. 在 `mcp_server/tools/` 下创建新工具模块
2. 在 `mcp_server/server.py` 中注册工具
3. 更新工具描述和schema

### 添加新的检索策略
1. 在 `mcp_server/retrieval/` 下实现新策略
2. 在工具中调用新策略
3. 添加相应测试

## 故障排除

### 常见问题
1. **连接失败**: 检查 Neo4j 和 Notion API 配置
2. **同步异常**: 查看 `logs/chimera_errors.log`
3. **性能问题**: 调整 `sync_interval_minutes` 和 `rate_limit`

### 日志分析
- 系统日志: `logs/chimera.log`
- 错误日志: `logs/chimera_errors.log`
- 使用 `--debug` 参数获取详细日志

## 部署清单

1. ✅ 配置文件设置完成
2. ✅ Neo4j 数据库运行正常
3. ✅ Notion API 密钥有效
4. ✅ Gemini API 密钥有效
5. ✅ 部署检查通过
6. ✅ 功能测试通过
7. ✅ 健康检查通过

## 维护说明

- **监控**: 定期检查日志和系统状态
- **备份**: 定期备份 Neo4j 数据库
- **更新**: 关注依赖包安全更新
- **优化**: 根据使用情况调整配置参数

---

*本文档随项目发展持续更新*