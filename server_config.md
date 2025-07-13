# Chimera 服务器配置

## 架构说明

```
LLM Client (Claude Desktop) → MCP Server (CentOS) → Neo4j Database (宝塔面板+Docker)
```

## 服务器1：Neo4j 图数据库

**部署方式**：宝塔面板 + Docker
- **Web管理界面**：7474端口 (仅管理员访问)
- **数据库连接**：7687端口 (开放给MCP服务器)
- **认证信息**：neo4j/1qw23er4

## 服务器2：MCP Server

**运行环境**：python + uv
- **服务端口**：3000 (开放给LLM访问)
- **连接数据库**：neo4j://neo4j-server-ip:7687

### MCP Server 运行指令

```bash
# 后台启动两个服务
nohup uv run fastmcp_server.py --host 0.0.0.0 --port 3000 > mcp_server.log 2>&1 &
nohup uv run run_chimera.py > sync_service.log 2>&1 &

# 检查状态
ps aux | grep fastmcp_server
ps aux | grep run_chimera

# 查看日志
tail -f mcp_server.log
tail -f sync_service.log

# 停止服务
pkill -f fastmcp_server
pkill -f run_chimera
```

## 客户端配置

**Claude Desktop MCP 配置**：

```json
"chimera-memory": {
  "command": "npx",
  "args": [
    "mcp-remote",
    "http://47.236.15.187:3000/mcp/",
    "--header",
    "Authorization:Bearer sk-9a3f7c82-b617-4f01-bb5d-2d7f4f93b8",
    "--allow-http"
  ]
}
```

## 端口开放要求

### Neo4j 服务器
- 7474/tcp：Web管理界面
- 7687/tcp：数据库连接

### MCP 服务器  
- 3000/tcp：MCP服务接口

## 数据流向

1. **Claude Desktop** 通过 mcp-remote 连接 **MCP Server:3000**
2. **MCP Server** 连接 **Neo4j:7687** 查询图数据库
3. **同步服务** 定期从 Notion 同步数据到 Neo4j