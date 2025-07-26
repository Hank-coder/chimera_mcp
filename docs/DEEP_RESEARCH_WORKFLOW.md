# Deep Research MCP 完整运行流程文档

本文档详细说明了Deep Research MCP系统的完整工作原理和执行流程。

## 系统架构概览

Deep Research MCP采用Director-Worker多智能体架构，通过以下组件协作完成深度研究分析：

- **ContextEngineeringDirector** (总控智能体)：协调整个研究流程
- **OptimizedWorker** (工蜂智能体)：处理具体的页面分析任务
- **BaseAgent** (基础智能体)：提供共享的API调用和工具函数

## 完整执行流程

### 阶段1：输入验证与页面结构检查

**负责组件**：ContextEngineeringDirector  
**核心方法**：`orchestrate_research()` -> `validate_page_structure()`

1. **请求接收**：接收DeepResearchRequest包含：
   - `page_id`: 根页面ID (如："22eccc690d82804886bccac59dd32145")
   - `purpose`: 研究目的 (如："了解UNSW课程体系")
   - `research_complexity`: 复杂度级别 (overview/standard/detailed/comprehensive)
   - `max_pages`: 最大分析页面数 (默认10)
   - `depth`: 遍历深度 (固定4层)

2. **页面验证**：
   - 检查根页面是否存在且可访问
   - 验证页面是否有子节点（通过Neo4j图数据库查询）
   - 统计子页面数量并评估研究范围
   - 如果验证失败，抛出异常并终止流程

### 阶段2：子图BFS遍历

**负责组件**：ContextEngineeringDirector  
**核心方法**：`notion_client.get_child_pages_bfs()`

1. **BFS遍历执行**：
   - 从根页面开始，按层级遍历4层深度
   - 通过Neo4j图数据库执行CHILD_OF关系查询
   - 收集页面元数据：ID、标题、标签、层级、最后编辑时间、URL
   - 限制最大20个候选页面（与max_pages参数一致）

2. **候选页面筛选**：
   - 按距离根页面的层级排序
   - 优先保留层级较低（更接近根页面）的页面
   - 生成候选页面列表用于后续分簇

### 阶段3：语义分簇

**负责组件**：ContextEngineeringDirector  
**核心方法**：`semantic_clustering()`

1. **簇数计算**：
   - 根据页面数量动态计算最优簇数
   - 页面≤10: 3个簇，页面≤30: 4个簇，页面≤60: 5个簇，否则6个簇
   - 簇数不超过4个Worker的限制（系统固定使用4个Worker）

2. **Gemini语义分簇**：
   - 调用`call_gemini_structured()`进行智能分簇
   - 基于页面标题、标签和元数据进行主题聚类
   - 生成包含page_ids和主题描述的分簇结果

3. **分簇后处理**：
   - 构建页面ID到页面数据的映射
   - 确保所有页面都被分配到某个簇中
   - 处理未分配页面（添加到最小簇）

4. **降级策略**：
   - 如果语义分簇失败，使用标签分簇
   - 再失败则使用简单负载均衡分簇

### 阶段4：4个Worker并发处理

**负责组件**：ContextEngineeringDirector + OptimizedWorker  
**核心方法**：`dispatch_workers()` -> `worker.process_cluster()`

1. **Worker创建与调度**：
   - 为每个簇创建一个OptimizedWorker实例
   - 传递复杂度配置和研究目的给Worker
   - 使用`asyncio.gather()`并发执行所有Worker

2. **单个Worker处理流程** (在OptimizedWorker中)：

   **2.1 批量获取页面内容**：
   - 并发调用Notion API获取每个页面的详细内容
   - 包含文档文件处理，最大8000字符限制
   - 更新页面数据包含实际时间戳和字数统计

   **2.2 并发页面分析**：
   - 根据复杂度配置动态调整摘要长度：overview(800字)、standard(1200字)、detailed(1800字)、comprehensive(2500字)
   - 为每个页面创建基于复杂度的分析prompt，包含复杂度特定的关注领域和风格
   - 调用`call_gemini_simple()`获取符合复杂度要求的摘要
   - **输出格式**：`**页面标题** (YYYY-MM-DD)\n摘要内容`
   - 确保每个摘要包含：核心内容概述、与研究目的关联、主要价值点，长度根据复杂度动态调整

   **2.3 簇级摘要拼接**：
   - 直接拼接所有页面摘要，格式：`主题簇：{cluster_theme}\n\n页面摘要1\n\n页面摘要2...`
   - 返回纯文本字符串，无需复杂的结构化对象

3. **错误处理**：
   - Worker级别异常处理，返回降级结果
   - 页面级别异常处理，单个页面失败不影响整个簇

### 阶段5：结果直接拼接（跳过Reduce）

**负责组件**：ContextEngineeringDirector  
**核心方法**：`create_research_context_from_summaries()`

1. **摘要拼接**：
   - 直接拼接所有Worker返回的簇摘要
   - 添加研究复杂度和目的信息
   - 生成统一的执行摘要格式

2. **简化研究框架创建**：
   - 创建基础的ResearchFramework对象
   - 提取关键洞察（每个簇摘要的前100字符）
   - 设置未来方向建议

3. **最终ResearchContext构建**：
   - `executive_summary`: 包含所有簇摘要的完整文本
   - `topic_clusters`: 空列表（简化版本）
   - `top_pages`: 空列表（简化版本）
   - `key_insights`: 基于簇摘要提取的洞察
   - `research_scope`: 包含处理元数据

### 阶段6：最终验证与优化

**负责组件**：ContextEngineeringDirector  
**核心方法**：`finalize_research_context()`

1. **内容完整性验证**：
   - 检查执行摘要是否为空
   - 确保关键洞察至少有3条
   - 补充基础的处理元数据

2. **元数据更新**：
   - 记录最终处理时间
   - 统计API调用次数
   - 记录使用的Worker数量

## 关键技术特点

### 1. 简化架构设计
- **去除复杂的Reduce步骤**：Worker直接返回文本摘要，Director简单拼接
- **跳过结构化对象传递**：减少JSON解析错误，提高稳定性
- **降级策略完善**：每个阶段都有fallback机制

### 2. API调用优化
- **统一使用`call_gemini_simple()`**：避免JSON解析问题
- **智能节流控制**：每秒8个API调用限制
- **错误隔离**：单个API失败不影响整体流程

### 3. 输出格式标准化
- **页面摘要格式**：`**标题** (时间)\n摘要内容`
- **簇摘要格式**：`主题簇：{主题}\n\n页面摘要1\n\n页面摘要2...`
- **最终输出**：纯文本执行摘要，便于阅读和处理

### 4. 性能与稳定性
- **并发处理**：4个Worker并发，每个Worker内部3个并发页面分析
- **API成功率**：从37.5%提升到80%+
- **处理速度**：通常20-40秒完成分析
- **错误恢复**：多层级降级策略确保始终有输出

## 配置参数说明

### 研究复杂度配置
```python
RESEARCH_COMPLEXITY_CONFIGS = {
    "overview": 800字摘要, 高层概述
    "standard": 1200字摘要, 平衡分析  
    "detailed": 1800字摘要, 深度分析
    "comprehensive": 2500字摘要, 学术级研究
}
```

### 系统固定参数
- **Worker数量**: 4个 (降低并发压力)
- **遍历深度**: 4层 (平衡覆盖面和性能)
- **API限制**: 每秒8个调用
- **页面限制**: 最大20个候选页面（默认10，最大20）
- **摘要长度**: 每页面<250字

## 错误处理机制

### 1. 页面验证失败
- **错误**: 页面不存在或无子节点
- **处理**: 抛出ValueError，终止流程
- **用户反馈**: 明确的错误信息

### 2. BFS遍历失败  
- **错误**: 图数据库查询失败
- **处理**: 返回空列表，终止流程
- **降级**: 无（这是致命错误）

### 3. 语义分簇失败
- **错误**: Gemini API调用失败或JSON解析错误
- **处理**: 使用标签分簇
- **再次失败**: 使用负载均衡分簇

### 4. Worker处理失败
- **错误**: 单个Worker异常
- **处理**: 生成降级簇摘要
- **影响**: 不影响其他Worker

### 5. 页面分析失败
- **错误**: 单个页面API调用失败
- **处理**: 返回格式化的错误信息
- **影响**: 不影响簇内其他页面

## 使用示例

### MCP调用示例
```python
# 通过FastMCP调用
request = {
    "method": "deep_research", 
    "params": {
        "page_id": "22eccc690d82804886bccac59dd32145",
        "purpose": "了解UNSW计算机课程体系和学习路径", 
        "research_complexity": "standard",
        "max_pages": 15
    }
}
```

### 典型输出示例
```
基于 standard 级别的深度研究分析
研究目的：了解UNSW计算机课程体系和学习路径

==================================================

主题簇：核心课程

**COMP1511 Programming Fundamentals** (2024-03-15)
这是UNSW计算机科学的入门编程课程，主要教授C语言基础...

**COMP2521 Data Structures and Algorithms** (2024-03-10)  
高级数据结构课程，涵盖链表、树、图等核心概念...

主题簇：专业选修

**COMP3411 Artificial Intelligence** (2024-02-28)
人工智能课程介绍机器学习、搜索算法等AI核心技术...
```

## 监控与调试

### 日志级别
- **INFO**: 主要流程节点
- **DEBUG**: 详细的API调用信息  
- **WARNING**: 降级策略触发
- **ERROR**: 异常和失败情况

### 关键指标
- **API成功率**: 目标80%+
- **处理时间**: 通常20-40秒
- **内存使用**: <500MB峰值
- **并发控制**: 4 Worker × 3 页面 = 12个并发任务

## 未来优化方向

1. **智能缓存**: 页面内容和分析结果缓存
2. **动态负载均衡**: 根据系统负载调整Worker数量
3. **增量更新**: 基于页面更新时间的智能重分析
4. **质量评估**: 输出摘要质量的自动评估机制
5. **用户反馈**: 集成用户满意度评估和反馈循环

---

**最后更新**: 2024年12月 - v1.5.6优化版本  
**系统状态**: 生产就绪，API成功率80%+，平均处理时间30秒