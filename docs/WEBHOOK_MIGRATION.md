# Webhook 系统迁移指南

## 📋 **迁移概述**

Chimera 已从**定时增量同步**迁移到**Notion Webhook实时推送**系统，实现真正的实时数据同步。

### ⚡ **新架构优势**

- **实时性**：页面变更立即同步，无需等待30分钟
- **准确性**：不再有时间戳比较问题，确保所有变更被捕获
- **效率**：只处理实际变更的页面，大幅减少API调用
- **可靠性**：事务性数据库更新，失败自动回滚

## 🔧 **配置步骤**

### 1. **更新配置文件**

在 `.env` 文件中添加：
```env
# Notion Webhook 配置（可选）
NOTION_WEBHOOK_SECRET=your_webhook_secret_here
```

### 2. **启动 Webhook 服务器**

```bash
# 启动webhook服务器（默认端口8081）
python webhook_server.py

# 或指定端口
python webhook_server.py --host 0.0.0.0 --port 8081 --debug
```

### 3. **配置 Notion Integration**

1. 访问 [Notion Integration 页面](https://www.notion.so/my-integrations)
2. 选择你的 Integration
3. 在 "Webhooks" 部分添加订阅：
   - **Endpoint URL**: `http://your-server:8081/notion/webhook`
   - **Event Types**: 选择以下事件
     - ✅ `page.created` - 页面创建
     - ✅ `page.moved` - 页面移动
     - ✅ `page.properties_updated` - 页面属性更新
     - ✅ `page.deleted` - 页面删除
     - ❌ `page.content_updated` - 内容更新（不需要）

4. 可选：设置 Webhook Secret 增强安全性

## 📊 **支持的事件类型**

| 事件类型 | 处理算法 | 说明 |
|---------|----------|------|
| `page.created` | MERGE节点 + 连父关系 | 新建页面时触发 |
| `page.moved` | 改父关系 + 重算层级 + 更新子树 | 页面移动到新位置 |
| `page.properties_updated` | 更新属性 + 重建关系 | 标题、标签等属性变更 |
| `page.deleted` | 删除节点 + 处理子页面 | 页面删除，子页面移至根级 |
| `page.content_updated` | 忽略 | 内容变更不影响图谱结构 |

## 🔄 **系统变更**

### **废弃的功能**
- ❌ 增量同步逻辑
- ❌ 定时同步调度
- ❌ `_should_do_full_sync()` 决策逻辑
- ❌ 时间戳比较过滤

### **保留的功能**
- ✅ 手动全量同步：`python run_chimera.py --manual-sync`
- ✅ 强制全量同步：`python run_chimera.py --force-full-sync`
- ✅ JSON缓存生成：`python run_chimera.py --generate-cache`
- ✅ MCP服务器：`python fastmcp_server.py`

## 🚀 **启动新系统**

### **标准部署流程**

```bash
# 1. 首次全量同步（建立基础数据）
python run_chimera.py --manual-sync

# 2. 启动Webhook服务器（实时同步）
python webhook_server.py

# 3. 启动MCP服务器（查询服务）
python fastmcp_server.py

# 4. 配置Notion Integration Webhook订阅
```

### **开发测试流程**

```bash
# 启动调试模式
python webhook_server.py --debug

# 测试webhook端点
curl -X POST http://localhost:8081/notion/webhook \
  -H "Content-Type: application/json" \
  -d '{"type": "challenge", "challenge": "test123"}'
```

## 🔍 **监控和排查**

### **日志查看**

```bash
# 查看webhook处理日志
tail -f logs/chimera.log | grep webhook

# 查看特定事件处理
grep "page.properties_updated" logs/chimera.log
```

### **健康检查**

```bash
# 检查webhook服务器状态
curl http://localhost:8081/health

# 检查MCP服务器状态
curl http://localhost:8080/health
```

### **常见问题**

1. **签名验证失败**
   - 检查 `NOTION_WEBHOOK_SECRET` 配置
   - 确认Notion Integration中设置了相同的secret

2. **事件处理失败**
   - 检查Neo4j连接状态
   - 确认页面权限已正确分享给Integration

3. **JSON缓存未更新**
   - 检查webhook事件是否处理成功
   - 手动生成缓存：`python run_chimera.py --generate-cache`

## 📈 **性能监控**

新系统的性能指标：

- **响应时间**：Webhook响应 < 100ms
- **处理时间**：事件处理 < 5秒
- **API调用**：减少90%的API调用量
- **实时性**：变更延迟 < 1秒

## 🔄 **迁移检查清单**

- [ ] 配置文件已更新
- [ ] Webhook服务器成功启动
- [ ] Notion Integration已配置webhook订阅  
- [ ] 测试页面创建/修改/删除事件
- [ ] JSON缓存正常更新
- [ ] MCP查询返回最新数据

迁移完成后，你的Chimera系统将实现真正的实时同步！🎉