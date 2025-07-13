## 开发规范

为确保项目的可维护性、可扩展性及团队协作效率，请开发成员严格遵循以下规范：

1. **需求导向开发**  
   - 在开始编码前，必须认真阅读并理解相关的需求文档（PRD、技术方案、接口协议等）。  
   - 如有疑问，应在开发前及时与产品经理或架构师沟通确认，避免因误解导致返工。

2. **优先复用与增量修改**  
   - **禁止盲目新建文件**：在新建模块或类文件前，必须浏览现有项目结构与历史代码。  
   - 若已有模块逻辑相关，应优先在现有文件中扩展或复用，避免重复造轮子与结构分裂。

3. **目录结构与命名规范**  
   - 所有代码文件必须放置在预定义的目录中，**严禁随意创建目录或平铺文件结构**。  
   - 例如：**所有的testing文档放在tests/里面 report放在report/**
   - 命名需符合项目约定（如：小写+下划线，CamelCase，特定前缀等），以提升可读性与一致性。  
   - 不得在主目录下直接新增源文件或脚本，应依据功能划分归类存放。

4. **文件与模块粒度控制**  
   - 文件大小应合理控制，避免出现**巨型类（God Class）**或**超长脚本**，建议单文件专注单一职责。  
   - 拆分模块时，应保持解耦、内聚、清晰边界，避免模块间隐式依赖。

5. **代码结构要求** ⭐  
   - **所有与LLM交互都需要使用Pydantic格式化，统一放在 `core/models.py`**  
   - **所有prompt模板放在 `prompts/` 文件夹，使用LangChain的PromptTemplate**  
   - **严禁在业务逻辑代码中硬编码prompt字符串**  
   - **所有LLM API调用必须有完整的类型提示和错误处理**


# 个人AI记忆核心 (Project Chimera) - 产品设计文档
## 1. 项目愿景与核心原则
### 1.1 项目愿景
打造一个与我共生的、可进化的个人认知中枢。它不仅是过去记忆的存储器，更是未来创造的加速器，让 AI 成为真正懂我、助我成长的"第二大脑"。

### 1.2 核心设计原则
- 图谱即索引 (Graph as Index): 本项目的核心哲学。Notion 是唯一的事实源头和内容载体；图数据库是其上的一层智能关系网络。系统通过查询图谱找到"路"，然后回到Notion读取详细内容。
- 不重复原则 (No Duplication): 严格遵守数据极简，图数据库不存储Notion页面正文，仅存储关系和元数据，从根本上避免数据一致性问题。
- 用户无感 (Seamless Experience): 所有后台同步和索引工作对用户透明，用户只需在Notion中自然地记录和组织。

## 2. 数据模型
### 2.1 统一节点模型：:NotionPage
整个图谱只使用一种核心节点，通过属性来区分其具体类型和状态。

| 属性 | 类型 | 来源 | 作用 |
|------|------|------|------|
| notionId | String | Notion API | 唯一主键，连接图谱与Notion的桥梁。 |
| title | String | Notion API | 方便识别和基础搜索。 |
| type | String | Notion API | 区分对象类型 (page, database, block)。 |
| tags | List<String> | Notion API | 页面的标签，用于主题聚类。 |
| embedding | Vector | AI生成 | AI导航核心，基于标题和摘要生成，用于语义搜索。 |
| lastEditedTime | DateTime | Notion API | 增量同步的关键，判断页面是否需要更新。 |
| url | String | Notion API | 方便从任何工具直接跳转回Notion源页面。 |

### 2.2 五种核心关系模型
通过五种精炼的关系类型，捕捉Notion中的结构与语义。

| 关系类型 | 模型 | 来源 | 作用 |
|----------|------|------|------|
| CHILD_OF | (:Page)-[:CHILD_OF]->(:Page) | 页面parent属性 | 结构骨架，映射Notion的页面层级。 |
| LINKS_TO | (:Page)-[:LINKS_TO]->(:Page) | 页面内链[[...]] | 显式引用，连接您手动关联的两个想法。 |
| RELATED_TO | (:Page)-[:RELATED_TO]->(:Page) | Database的relation属性 | 结构化关联，利用Notion Database的强大功能。 |
| MENTIONS | (:Page)-[:MENTIONS]->(:Page) | 页面内@提及 | 实体提及，常用于连接到人员或特定项目页面。 |
| HAS_TAG | (:Page)-[:HAS_TAG]->(:Tag) | 页面的tags属性 | 主题聚类，将不同层级的页面按主题连接起来。 |

## 3. 系统架构与工作流
### 3.1 精简双服务架构 uv管理
- 后台同步服务 (The Archivist - 档案保管员): 独立、低频运行的进程。唯一职责是忠实地读取Notion，并使用Graphiti根据数据模型更新Neo4j图谱索引。（只有监测到变化才更新）
- MCP检索服务 (The Navigator - 导航员): 轻量、快速、无状态的服务。唯一职责是响应LLM的请求，在图谱中快速搜索，并返回一个notionId列表 (Graphiti里面自带MCP服务) 

### 3.2 核心查询工作流
1. 查询发起： 用户向集成了本系统的AI应用提问。
2. 关系导航： MCP检索服务接收查询，在图数据库中通过语义搜索（embedding）和关系遍历（CHILD_OF, LINKS_TO等）找到最相关的一批页面的notionId。
3. 返回ID列表： MCP服务将去重和排序后的notionId列表返回给AI应用。
4. 内容获取： AI应用根据ID列表，通过Notion API实时、并发地获取这些页面的最新原文。
5. 上下文构建： AI应用将"关系摘要"（例如："找到项目A，它提到了张三"）和"页面原文"组合成一个丰富的上下文。
6. 生成回答： AI应用将此上下文连同原始问题一起发送给大语言模型（LLM），获得精准、深刻的回答。
7. 输出和输入必须格式化 使用pydantic

## 4. "一步到位"的实施计划
### 4.1 核心同步逻辑
后台同步服务需严格遵循以下步骤：
1. 通过Notion API获取所有需要索引的页面元数据。
2. 遍历列表，在Neo4j中MERGE :NotionPage节点并更新其属性。
3. 对每个页面，根据其parent_id、[[...]]内链、relation属性、@提及和tags属性，分别MERGE对应的五种核心关系。

### 4.2 最小可行工具集 (MCP Toolkit)
| 工具名称 | 参数 | 用途 |
|----------|------|------|
| search(query: str, limit: int) | query | 入口工具。执行语义搜索，返回最相关的notionId列表。 |
| expand(page_ids: list, depth: int) | page_ids | 扩展工具。从给定的页面ID出发，沿所有关系扩展depth层。 |
| get_content(page_ids: list) | page_ids | 内容工具。由最终的LLM客户端调用，从Notion获取原文。 |

### 4.3 3周开发路线图
- 第一周：核心同步
  - 目标： 将Notion结构成功映射到Neo4j。
  - 任务： 搭建Notion API连接，实现核心同步逻辑，手动触发并验证图谱数据正确性。使用repo。https://github.com/ramnes/notion-sdk-py
- 第二周：MCP检索
  - 目标： 让AI能够通过图谱进行查询。
  - 任务： 搭建基础的MCP服务，实现search和expand两个核心工具。
- 第三周：集成与优化
  - 目标： 拥有一个可用的端到端系统。
  - 任务： 将MCP服务集成到您的LLM客户端中，并实现简单的定时同步任务。

## 5. 项目优势
- 开发极简: 关系提取逻辑清晰，不依赖复杂的NLP，完美复用Notion的结构化数据。
- 维护轻松: 单向数据流，图谱作为无状态索引，无需担心数据同步冲突。
- 实时一致: 内容永远从Notion实时获取，保证了信息的最新性。
- 高度可扩展: 未来若发现新的关联模式，只需在同步逻辑中增加一种关系提取规则即可，核心架构保持不变。

## 项目目录结构
personal-ai-memory/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── pyproject.toml                 # 项目配置和依赖
│
├── config/                        # 配置管理
│   ├── __init__.py
│   ├── settings.py               # 环境变量和配置
│   └── logging.py                # 日志配置
│
├── core/                          # 核心业务逻辑
│   ├── __init__.py
│   ├── models.py                 # 数据模型定义 (包含所有LLM交互的Pydantic模型)
│   ├── graphiti_client.py        # Graphiti封装客户端
│   ├── notion_client.py          # Notion API客户端
│   └── intent_search.py          # 意图搜索系统 (使用Gemini 2.0 Flash)
│
├── sync_service/                  # 后台同步服务
│   ├── __init__.py
│   ├── main.py                   # 同步服务入口
│   ├── notion_scanner.py         # Notion结构扫描
│   ├── relation_extractor.py     # 关系提取器
│   ├── graph_updater.py          # 图数据库更新器
│   └── scheduler.py              # 定时任务调度
│
├── mcp_server/                    # MCP检索服务
│   ├── __init__.py
│   ├── server.py                 # MCP服务器主体
│   ├── tools/                    # MCP工具集
│   │   ├── __init__.py
│   │   ├── search_tools.py       # 搜索相关工具
│   │   ├── context_tools.py      # 上下文获取工具
│   │   └── navigation_tools.py   # 导航遍历工具
│   └── retrieval/                # 检索策略
│       ├── __init__.py
│       ├── graph_retriever.py    # 图数据库检索
│       ├── notion_retriever.py   # Notion内容检索
│       └── hybrid_retriever.py   # 混合检索策略
│
├── agents/                        # LangGraph Agent (可选)
│   ├── __init__.py
│   ├── retrieval_agent.py        # 检索优化Agent
│   ├── context_agent.py          # 上下文组织Agent
│   └── planning_agent.py         # 查询规划Agent
│
├── prompts/                       # 提示词模板管理 ⭐
│   ├── __init__.py
│ 
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   ├──  Daemon_Manager.py        # 按照项目结构，协调运行两个核心服务 MCP Retrieve + Neo4j实时更新
│   ├── text_processing.py        # 文本处理工具
│   ├── notion_parser.py          # Notion内容解析
│   └── graph_utils.py            # 图操作工具
│
├── report/  # 项目更新的汇报文档
├── scripts/                       # 脚本工具
│   ├── setup_database.py         # 数据库初始化
│   ├── manual_sync.py            # 手动同步脚本
│   └── health_check.py           # 健康检查脚本
│
└── tests/                         # **测试代码放置在此处**
    ├── __init__.py 
    ├── notion/
    ├── sync_service/
    ├── mcp_server/
    └── utils/

