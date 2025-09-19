## 开发规范

为确保项目的可维护性、可扩展性及团队协作效率，请开发成员严格遵循以下规范：

1. **需求导向开发**  
   - 在开始编码前，必须认真阅读并理解相关的需求文档（PRD、技术方案、接口协议等）。  
   - 如有疑问，应在开发前及时与产品经理或架构师沟通确认，避免因误解导到返工。

2. **优先复用与增量修改**  
   - **禁止盲目新建文件**：在新建模块或类文件前，必须浏览现有项目结构与历史代码。  
   - 若已有模块逻辑相关，应优先在现有文件中扩展或复用，避免重复造轮子与结构分裂。

3. **目录结构与命名规范**  
   - 所有代码文件必须放置在预定义的目录中，**严禁随意创建目录或平铺文件结构**。  
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

## 快速开始

### 环境要求
- Python 3.11+
- Neo4j 5.0+
- UV包管理器

### 快速启动（冷启动）
```bash
# 1. 克隆项目
git clone <repo-url>
cd Chimera

# 2. 安装依赖
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑.env文件，配置必要的API密钥

# 4. 启动Neo4j数据库
# 确保Neo4j运行在localhost:7687

# 5. 启动系统
uv run python run_chimera.py
```

### 配置项说明 （.env文件中）
- `NOTION_TOKEN`: Notion API密钥
- `NEO4J_PASSWORD`: Neo4j数据库密码
- `GEMINI_API_KEY`: Google Gemini API密钥
- `CHIMERA_API_KEY`: 系统Bearer认证密钥（可选）
- `GEMINI_MODEL`： 默认使用的llm模型
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

### 2.2 核心关系模型
通过精炼的关系类型，捕捉Notion中的结构与语义。

| 关系类型 | 模型 | 来源 | 作用 |
|----------|------|------|------|
| CHILD_OF | (:Page)-[:CHILD_OF]->(:Page) | 页面parent属性 | 结构骨架，映射Notion的页面层级。 |

待扩展：
| LINKS_TO | (:Page)-[:LINKS_TO]->(:Page) | 页面内链[[...]] | 显式引用，连接您手动关联的两个想法。 |
| RELATED_TO | (:Page)-[:RELATED_TO]->(:Page) | Database的relation属性 | 结构化关联，利用Notion Database的强大功能。 |
| MENTIONS | (:Page)-[:MENTIONS]->(:Page) | 页面内@提及 | 实体提及，常用于连接到人员或特定项目页面。 |
| HAS_TAG | (:Page)-[:HAS_TAG]->(:Tag) | 页面的tags属性 | 主题聚类，将不同层级的页面按主题连接起来。 |

## 3. 系统架构与工作流
### 3.1 精简双服务架构 uv管理
- **后台同步服务 (The Archivist - 档案保管员)**: 独立、低频运行的进程。唯一职责是忠实地读取Notion，并使用Graphiti根据数据模型更新Neo4j图谱索引。
  - 同步策略：智能混合同步（增量+全量）
  - 增量同步：默认30分钟间隔，检测变化后更新
  - 全量同步：隔天北京时间4:00-4:30自动执行，或超过3天强制执行
  - 包含删除检测：全量同步时会清理Notion中已删除的页面
- **MCP检索服务 (The Navigator - 导航员)**: 轻量、快速、无状态的服务。唯一职责是响应LLM的请求，在图谱中快速搜索，并返回一个notionId列表。
  - 基于FastMCP实现，支持Graphiti的语义搜索
  - 包含意图搜索系统，使用Gemini 2.0 Flash进行查询优化 

### 3.2 核心查询工作流
1. 查询发起： 用户向集成了本系统的AI应用提问。
2. 关系导航： MCP检索服务接收查询，在图数据库中通过 LLM 和关系遍历（CHILD_OF, LINKS_TO等）找到最相关的一批页面的notionId。
3. 返回ID列表： MCP服务将去重和排序后的notionId列表返回给AI应用。
4. 内容获取： AI应用根据ID列表，通过Notion API实时、并发地获取这些页面的最新原文。
5. 上下文构建： AI应用将"关系摘要"（例如："找到项目A，它提到了张三"）和"页面原文"组合成一个丰富的上下文。
6. 生成回答： AI应用将此上下文连同原始问题一起发送给大语言模型（LLM），获得精准、深刻的回答。
7. 输出和输入必须格式化 使用pydantic

## 4. "一步到位"的实施计划
### 4.1 核心同步逻辑
后台同步服务需严格遵循以下步骤：
1. 通过Notion API获取所有需要索引的页面元数据。
2. 遍历列表，在本地JSON缓存及Neo4j NotionPage节点更新属性 （分全量和增量同步）
3. 对每个页面，根据其parent_id、[[...]]内链、relation属性、@提及和tags属性，分别MERGE对应的五种核心关系。

### 4.2 MCP工具集（已完整实现）✅

#### 1. **🧠 个人记忆搜索（Notion）** - intent_search
**核心功能**: 从第二大脑（Notion）中查找相关笔记、记录、项目、总结等内容。

**参数列表**:
- `query` (str, 必填): 搜索关键词或短语，支持时间信息，例如："上周碳中和计划"
- `confidence_threshold` (float, 默认0.8): 最低置信度阈值，范围0.5-1.0，用于过滤搜索结果
- `search_results` (int, 默认3): 返回的最大搜索结果条数
- `expansion_depth` (int, 默认1): 路径扩展深度，决定关联更多上下游页面的层级
- `max_file_content_length` (int, 默认8000): 单个文档文件内容最大字符数限制
- `max_page_content_length` (int, 默认10000): 单个Notion页面内容最大字符数限制

**技术实现**:
- 使用Gemini 2.0 Flash进行意图理解和查询优化
- 基于Graphiti的语义搜索和关系遍历
- 支持置信度评估和路径扩展
- 自动提取文档文件内容（PDF、Word等）
- 返回完整路径内容和时间戳信息

**返回结果**:
```json
{
  "success": true,
  "data": {
    "paths": [
      {
        "path": "Hank -> 项目管理 -> 碳中和计划",
        "confidence": 0.95,
        "last_edited_time": "2024-01-15T10:30:00Z",
        "path_contents": [/* 路径中所有页面的详细内容 */],
        "total_pages": 3
      }
    ],
    "search_summary": "找到 3 条相关路径",
    "intent_keywords": ["碳中和", "计划", "项目管理"]
  },
  "message": "找到 3 个相关结果"
}
```

#### 2. **🌐 社交关系搜索（微信）** - relationship_search
**核心功能**: 从微信聊天记录中查找人际关系、群组成员、活动参与等社交信息。

**参数列表**:
- `query` (str, 必填): 关系查询问题，可以是人名、项目名或关系问题
- `max_results` (int, 默认3, 最大10): 返回的最大搜索结果数量

**典型查询**:
- 人名查询：例如 "敏哥"、"JZX"
- 项目查询：例如 "GREEN项目"、"研发项目"
- 关系查询：例如 "谁参与了GREEN项目"、"肥猫是什么角色"

**技术实现**:
- 基于实体识别和关系图谱的智能搜索
- 支持模糊匹配和别名识别
- 自动分析查询类型（人物、项目、关系）
- 生成结构化的关系摘要

**返回结果**:
```json
{
  "success": true,
  "data": {
    "relationships": [/* 匹配的关系实体数组 */],
    "formatted_answer": "敏哥在GREEN研发项目中担任核心开发角色，参与了架构设计和技术选型...",
    "query_analysis": {
      "query_type": "person_role",
      "entities": ["敏哥", "GREEN项目"],
      "intent": "查询人物在项目中的角色"
    },
    "processing_time_ms": 150
  },
  "message": "找到 3 个相关关系"
}
```

#### 3. **🔬 智能深度研究** - deep_research ✨**新功能**
**核心功能**: 基于根页面进行深度研究分析，生成大模型可直接使用的结构化研究上下文。

**参数列表**:
- `page_id` (str, 必填): 研究起点页面ID
- `purpose` (str, 必填): 研究目的和关注点（后期用于工蜂判断内容关联度）
- `max_pages` (int, 默认10, 范围5-20): 返回的最大页面数量
- `research_complexity` (str, 默认"standard"): 研究复杂度级别

**研究复杂度级别**:
- `overview`: 高层概览，突出核心结论和趋势（压缩率30%，目标长度800字符）
- `standard`: 平衡分析，核心观点+支撑证据（压缩率50%，目标长度1200字符）
- `detailed`: 深度分析，包含方法论和案例（压缩率60%，目标长度1800字符）
- `comprehensive`: 学术级分析，完整理论框架（压缩率80%，目标长度2500字符）

**系统架构**:
- **固定遍历深度**: 4层子页面（发现更多候选页面）
- **固定Worker数量**: 4个并发智能体（优化并发性能）
- **语义分簇**: 基于内容相似性自动分组
- **关联度过滤**: 基于研究目的过滤无关内容（阈值0.2，降级0.1）
- **KV Cache优化**: 稳定前缀设计，最大化缓存命中率

**技术实现**:
- **Director-Worker架构**: 1个总控智能体 + 4个处理工蜂
- **多Agent协作**: 语义分簇 → 并发处理 → 关联度过滤 → 综合分析
- **Purpose-driven过滤**: 每个Worker根据研究目的评估内容关联度
- **结构化压缩**: 保持信息完整性的同时优化token使用
- **错误恢复**: 完整的降级策略和容错机制

**返回结果**:
```json
{
  "success": true,
  "data": {
    "research_context": {
      "executive_summary": "基于standard模式的综合摘要，整合了6个主题簇的核心观点...",
      "topic_clusters": [
        {
          "cluster_id": "worker_0",
          "theme": "主题簇_1",
          "pages": [/* 页面分析结果数组 */],
          "cluster_synthesis": "该簇的400-600字综合分析...",
          "representative_quotes": ["代表性引用1", "代表性引用2"],
          "cross_references": ["与其他主题的关联说明"]
        }
      ],
      "top_pages": [/* 按重要性排序的顶级页面分析 */],
      "key_insights": [
        "洞察1：跨主题的重要发现或趋势",
        "洞察2：具有指导意义的核心原则"
      ],
      "supporting_evidence": [/* 支撑证据数组 */],
      "research_framework": {
        "problem_definition": "基于内容总结的核心研究问题",
        "theoretical_foundation": "理论基础和概念框架",
        "methodology_insights": "从内容中提炼的方法论指导",
        "expected_contributions": "可能的学术和实践贡献"
      },
      "future_directions": [/* 后续研究方向建议 */]
    },
    "complexity_applied": "standard",
    "pages_analyzed": 10,
    "processing_metadata": {
      "workers_used": 6,
      "depth_traversed": 3,
      "api_calls_made": 25,
      "processing_time_seconds": 45.2,
      "clusters_formed": 4,
      "top_pages_selected": 10
    }
  },
  "message": "研究完成：standard级分析，10个顶级页面，4个主题簇"
}
```

**典型用途场景**:
- **学术研究**: 从大量资料中提取结构化研究框架
- **项目分析**: 深度分析项目文档，生成洞察报告
- **知识整合**: 将分散的笔记整合成系统性知识
- **决策支持**: 为复杂决策提供全面的背景分析
- **内容创作**: 为写作提供深度研究素材

### 4.3 MCP工具优势特性
- **智能意图理解**: 使用Gemini 2.0 Flash进行查询优化
- **多模态内容**: 支持文本、文档、图片等多种格式
- **关联度过滤**: 基于目的的智能内容筛选
- **并发处理**: 多Agent并发架构，高效处理大量内容
- **容错机制**: 完整的错误处理和降级策略
- **Token优化**: KV Cache优化，降低API调用成本
- **实时同步**: 内容永远从Notion实时获取，保证最新性
- **结构化输出**: 严格的Pydantic模型，确保数据质量

### 4.3 项目进展状态 ✅
项目已完成核心功能开发，当前状态：
- ✅ **第一周完成**：核心同步服务
  - Notion API连接与数据提取
  - 智能同步调度器（增量+全量混合策略）
  - Graphiti客户端集成
- ✅ **第二周完成**：MCP检索服务
  - FastMCP服务器实现
  - 语义搜索与意图理解
  - 文件内容提取与处理
- ✅ **第三周完成**：集成优化
  - 端到端系统测试
  - 日志监控与错误处理
  - 配置管理与部署脚本

## 5. 项目优势
- 开发极简: 关系提取逻辑清晰，不依赖复杂的NLP，完美复用Notion的结构化数据。
- 维护轻松: 单向数据流，图谱作为无状态索引，无需担心数据同步冲突。
- 实时一致: 内容永远从Notion实时获取，保证了信息的最新性。
- 高度可扩展: 未来若发现新的关联模式，只需在同步逻辑中增加一种关系提取规则即可，核心架构保持不变。

## 项目目录结构（实际版本）
```
Chimera/
├── README.md
├── requirements.txt
├── pyproject.toml                 # uv项目配置和依赖管理
├── uv.lock                       # 依赖锁定文件
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
│   ├── file_extractor.py         # 文件内容提取器
│   └── correct_mcp_chain.py      # MCP链式调用处理
│
├── sync_service/                  # 后台同步服务
│   ├── __init__.py
│   ├── sync_service.py           # 同步服务主体（包含智能同步策略）
│   ├── notion_scanner.py         # Notion结构扫描
│   ├── graph_updater.py          # 图数据库更新器
│   └── scheduler.py              # 定时任务调度
│
├── agents/                        # 智能Agent系统
│   ├── __init__.py
│   └── intent_search.py          # 意图搜索系统 (使用Gemini 2.0 Flash)
│
├── prompts/                       # 提示词模板管理 ⭐
│   ├── __init__.py
│   └── intent_evaluation.py      # 意图评估提示词
│
├── utils/                         # 工具函数
│   ├── __init__.py
│   └── fastmcp_utils.py          # FastMCP工具函数
│
├── scripts/                       # 脚本工具
│   ├── __init__.py
│   └── setup_database.py         # 数据库初始化
│
├── tests/                         # 测试代码
│   ├── __init__.py
│   ├── notion/                   # Notion相关测试
│   ├── sync_service/             # 同步服务测试
│   ├── mcp_server/               # MCP服务器测试
│   └── demo_intent_search.py     # 意图搜索演示
│
├── logs/                          # 日志文件
├── llm_cache/                     # LLM缓存
├── docs/                          # 技术文档
│
├── fastmcp_server.py             # FastMCP服务器入口
├── run_chimera.py                # 系统启动脚本
└── server_config.md              # 服务器配置文档
```

