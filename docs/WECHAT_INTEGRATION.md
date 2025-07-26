# Chimera微信关系图谱集成设计方案

## 1. 系统架构概览

### 1.1 双模态智能检索架构

Chimera v1.4将支持两种并行的检索模式：

## 🎯 功能概述

### 核心特性
- **双模检索**：`intent_search`（Notion文档）+ `relationship_search`（微信关系）
- **LLM智能选择**：自动判断使用哪个MCP function
- **独立数据库**：微信数据存储在专门的`weichat`数据库中
- **手动控制**：完全手动的JSON添加和同步流程

### 技术架构
```
Chimera/
├── core/
│   ├── models.py                 # 新增微信相关Pydantic模型
│   └── wechat_search.py         # 微信关系图谱检索引擎
├── sync_service/
│   └── wechat_sync.py           # JSON→Graphiti同步引擎
├── prompts/
│   └── wechat_analysis.py       # Gemini分析提示词
├── scripts/
│   └── wechat_sync.py           # 独立同步脚本
└── fastmcp_server.py            # 扩展：新增relationship_search
```

## 🚀 快速开始

### 1. 环境准备

#### 创建独立Neo4j数据库
```bash
# 连接到Neo4j
cypher-shell -u neo4j -p your_password

# 创建weichat数据库
CREATE DATABASE weichat;

# 验证数据库创建
SHOW DATABASES;
```

#### 确保目录结构
```bash
mkdir -p local_data/weichat/group
mkdir -p local_data/weichat/person
```

### 2. 配置文件

在`.env`文件中确保以下配置：
```env
# Neo4j配置
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password

# Gemini配置
GEMINI_API_KEY=your_gemini_api_key

# 微信数据配置（可选，有默认值）
WECHAT_DATA_PATH=local_data/weichat
WECHAT_NEO4J_DATABASE=weichat
WECHAT_SYNC_ENABLED=true
```

### 3. 数据同步

#### 方式1：使用独立脚本（推荐）
```bash
# 查看帮助
python scripts/wechat_sync.py --help

# 增量同步新文件
python scripts/wechat_sync.py incremental

# 强制同步所有文件
python scripts/wechat_sync.py force

# 查看同步状态
python scripts/wechat_sync.py status

# 验证JSON文件格式
python scripts/wechat_sync.py validate
```

#### 方式2：程序化调用
```python
from sync_service.wechat_sync import WechatSyncEngine

# 初始化同步引擎
sync_engine = WechatSyncEngine()

# 增量同步
report = await sync_engine.incremental_sync()

# 强制同步所有文件
report = await sync_engine.force_sync_all()

# 查看状态
status = sync_engine.get_sync_status()
```

### 4. 启动MCP服务器

```bash
# 启动包含双MCP Function的服务器
python fastmcp_server.py
```

服务器将在 `http://localhost:3000/mcp` 提供以下工具：
- `intent_search`：Notion文档检索
- `relationship_search`：微信关系图谱检索

## 📊 JSON数据格式

### 标准格式示例
```json
{
  "entities": [
    {
      "type": "Person",
      "name": "ゞ肥の猫ゞ",
      "id": "wechat_user_123"
    },
    {
      "type": "Context",
      "name": "肥肥窝",
      "description": "家庭群聊"
    }
  ],
  "relationships": [
    {
      "type": "MEMBER_OF",
      "source": "ゞ肥の猫ゞ",
      "target": "肥肥窝"
    },
    {
      "type": "KNOWS",
      "source": "ゞ肥の猫ゞ",
      "target": "妈妈",
      "relation": "母子"
    },
    {
      "type": "INVOLVE",
      "source": "ゞ肥の猫ゞ",
      "target": "AI项目",
      "time": "2024-01-05~2025-07-15"
    }
  ]
}
```

### 支持的关系类型
- **KNOWS**：人际关系（朋友、同学、母子、父子、项目合作等）
- **MEMBER_OF**：群组成员关系
- **INVOLVE**：活动参与关系（支持时间维度）

## 🔍 使用方法

### 在Claude Desktop中使用

系统会自动选择合适的MCP function：

```
用户：谁认识yvnn？
→ 系统自动选择 relationship_search

用户：我的碳中和计划在哪里？
→ 系统自动选择 intent_search

用户：肥肥窝的成员有哪些？
→ 系统自动选择 relationship_search
```

### 直接API调用

```python
from core.wechat_search import WechatRelationshipSearch

# 初始化搜索引擎
search_engine = WechatRelationshipSearch()

# 搜索关系
result = await search_engine.search(
    query="谁认识yvnn",
    max_results=10,
    include_context=True
)

# 获取人员档案
profile = await search_engine.get_person_profile("ゞ肥の猫ゞ")

# 获取群组成员
members = await search_engine.get_group_members("肥肥窝")

# 搜索两人关系
relationship = await search_engine.search_relationships("张三", "李四")
```

## 🎨 Episode生成策略

系统将JSON数据转换为6种类型的自然语言Episodes：

### 1. 人员身份Episode
```
ゞ肥の猫ゞ是一位用户，微信ID是wechat_user_123。
ゞ肥の猫ゞ活跃在多个社交圈子中，参与各种活动和项目。
```

### 2. 群组/上下文Episode
```
肥肥窝是一个群组，家庭群聊。
群成员包括：ゞ肥の猫ゞ, 妈妈, 爸爸。
这个群组是3人的交流空间。
```

### 3. 人际关系Episode
```
ゞ肥の猫ゞ和妈妈彼此认识，他们是母子关系。
ゞ肥の猫ゞ的微信ID是wechat_user_123，妈妈的微信ID是mom_user_456。
这种母子关系体现了他们之间的社会连接。
```

### 4. 群组成员关系Episode
```
ゞ肥の猫ゞ是肥肥窝的成员。
肥肥窝是家庭群聊，ゞ肥の猫ゞ在其中进行交流和互动。
```

### 5. 活动参与Episode
```
ゞ肥の猫ゞ参与了AI项目活动。
AI项目的内容是：人工智能相关的研发项目。
ゞ肥の猫ゞ的参与时间是2024年01月到2025年07月。
通过参与这个活动，ゞ肥の猫ゞ与其他参与者产生了互动和协作。
```

### 6. 综合社交场景Episode
```
在肥肥窝这个社交环境中，ゞ肥の猫ゞ, 妈妈, 爸爸形成了一个社交网络。
他们共同参与了以下活动：AI项目, 家庭聚会。
这个社交圈体现了成员间的多元化互动关系。
```

## 🔧 工作流程

### 1. 数据准备
- 手动创建符合格式的JSON文件
- 放置在`local_data/weichat/`目录中
- 支持嵌套目录结构

### 2. 数据同步
- 运行`python scripts/wechat_sync.py`
- 系统读取JSON并转换为Episodes
- 存储到Neo4j的`weichat`数据库中

### 3. 关系查询
- 启动FastMCP服务器
- 在Claude Desktop中进行自然语言查询
- 系统自动选择检索引擎并返回结果

## 📈 性能优化

### 搜索优化
- 使用Gemini 2.0 Flash进行查询分析
- 支持中心节点搜索提高精度
- 结果去重和相关性排序

### 缓存机制
- 同步状态本地缓存
- 处理文件记录避免重复同步
- 失败文件重试机制

## ⚠️ 注意事项

1. **数据库隔离**：微信数据存储在独立的`weichat`数据库中，与Notion数据完全分离
2. **手动控制**：所有同步操作都是手动触发，不会自动运行
3. **数据格式**：JSON文件必须严格遵循指定格式，否则同步会失败
4. **依赖关系**：需要Neo4j和Gemini API正常运行

## 🚨 故障排除

### 常见问题

1. **数据库连接失败**
   ```
   解决方案：确保Neo4j正在运行，并已创建weichat数据库
   ```

2. **JSON格式错误**
   ```bash
   # 使用验证命令检查文件格式
   python scripts/wechat_sync.py validate
   ```

3. **Gemini API错误**
   ```
   解决方案：检查GEMINI_API_KEY配置和网络连接
   ```

4. **同步失败**
   ```bash
   # 查看详细状态
   python scripts/wechat_sync.py status
   
   # 查看失败文件
   python scripts/wechat_sync.py status | grep "失败文件"
   ```

### 调试模式

启用调试日志：
```bash
python scripts/wechat_sync.py --log-level DEBUG status
```

### 重置数据

如需重置所有微信数据：
```bash
# 删除处理状态文件
rm local_data/weichat/processed_files.json

# 清空Neo4j数据库
cypher-shell -u neo4j -p your_password -d weichat
MATCH (n) DETACH DELETE n;

# 重新同步
python scripts/wechat_sync.py force
```

## 📚 API参考

### WechatSyncEngine

```python
class WechatSyncEngine:
    def __init__(self, data_path: str = None)
    
    async def incremental_sync(self) -> WechatSyncReport
    async def force_sync_all(self) -> WechatSyncReport
    async def sync_files(self, file_paths: List[Path]) -> WechatSyncReport
    
    def scan_new_files(self) -> List[Path]
    def get_all_files(self) -> List[Path]
    def get_sync_status(self) -> Dict[str, Any]
```

### WechatRelationshipSearch

```python
class WechatRelationshipSearch:
    def __init__(self)
    
    async def search(self, query: str, max_results: int = 10, 
                    include_context: bool = True) -> WechatSearchResponse
    
    async def get_person_profile(self, person_name: str) -> Dict[str, Any]
    async def get_group_members(self, group_name: str) -> Dict[str, Any]
    async def search_relationships(self, person1: str, person2: str) -> Dict[str, Any]
```

## 🔮 未来扩展

计划中的功能：
- 时间维度查询（"去年参与的项目"）
- 关系路径分析（"张三通过谁认识李四"）
- 社交网络可视化
- 批量数据导入工具
- 增量更新优化