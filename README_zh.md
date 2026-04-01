# Parquool

Parquool 是一个轻量级的 Python 库，提供对 Parquet 数据集的 SQL 式查询、分区写入、upsert/update/delete 操作，以及基于 openai-agents 的 Agent 包装器和内置的 RAG 支持。

该库旨在简化在使用 Parquet 文件作为本地或服务器存储时的常见数据管理场景。基于 DuckDB 提供高性能 SQL 查询能力，并支持将查询结果写回为分区 Parquet 文件。Agent 类提供了便捷、开箱即用的 openai-agents 接口。Collection 提供了方便的知识库管理工具，能帮助用户快速将知识库嵌入为向量数据库，方便 LLM 查询访问。

## 主要特性

- **DuckDB 后端存储**：使用 DuckDB 的 `parquet_scan` 创建视图，像操作数据库表一样查询 Parquet 文件
- **Upsert 操作**：支持按主键的合并语义和 Hive 风格分区写入
- **SQL 变异操作**：支持基于 SQL 的更新和删除操作，原子性替换目录内容
- **Pivot 操作**：同时支持 DuckDB PIVOT 和 pandas pivot_table
- **Agent 集成**：基于 openai-agents 的高级封装，支持 RAG 和会话管理
- **知识库管理**：基于 ChromaDB 的向量存储，支持嵌入式检索
- **实用工具**：可配置的日志记录器、HTTP 代理请求、邮件通知和网络搜索

## 安装

```bash
pip install parquool
```

可选依赖：
```bash
pip install "parquool[knowledge]"    # ChromaDB 和嵌入
pip install "parquool[websearch]"     # SerpAPI 搜索
pip install "parquool[mcp]"           # MCP 服务器
```

## 快速开始

### DuckTable

查询和管理 Parquet 文件目录：

```python
from parquool import DuckTable
import pandas as pd

# 打开数据集目录（如果不存在则创建）
dt = DuckTable('/path/to/parquet_dir', name='my_data', create=True)

# 带过滤和排序的查询
df = dt.select(
    columns=['id', 'value', 'date'],
    where='value > 100',
    order_by='date DESC',
    limit=50
)

# 按主键 upsert 并分区
new_rows = pd.DataFrame([
    {'id': 1, 'value': 42, 'date': '2024-01-01'},
    {'id': 2, 'value': 99, 'date': '2024-01-02'},
])
dt.upsert(new_rows, keys=['id'], partition_by=['date'])

# DuckDB PIVOT
pivot_df = dt.dpivot(
    index='date',
    columns='category',
    values='sales',
    aggfunc='sum'
)

# 合并分区
dt.compact(compression='zstd')
```

### DuckPQ

管理多个 Parquet 表：

```python
from parquool import DuckPQ

# 打开多表数据库
db = DuckPQ(root_path='/data/warehouse')

# 自动注册所有子目录为表
db.register()

# 查询单个表
df = db.select(
    table='sales',
    columns=['date', 'region', 'revenue'],
    where="region = 'US'",
    limit=100
)

# 跨表 SQL 连接
result = db.query("""
    SELECT s.date, s.revenue, p.product_name
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.date >= '2024-01-01'
""")
```

### 带 RAG 的 Agent

```python
from parquool import Agent, Collection

# 创建知识库
collection = Collection(
    default_collection='docs',
    embedding_model='text-embedding-3-small'
)
collection.load(['/path/to/docs'])

# 创建带 RAG 的 Agent
agent = Agent(
    name='assistant',
    collection=collection,
    rag_max_context=6000
)

# 运行查询
result = agent.run_sync("我们的退货政策是什么？")
print(result.final_output)
```

### 流式输出

```python
from parquool import Agent

agent = Agent(model_name='gpt-4')

# 同步流式输出
result = agent.run_streamed_sync('给我讲个故事')
```

### 会话管理

```python
from parquool import Agent

agent = Agent(session_db='/tmp/sessions.db')

# 使用特定会话运行
result1 = agent.run_sync('我叫张三', session_id='user_123')
result2 = agent.run_sync('我叫什么名字？', session_id='user_123')

# 获取对话历史
messages = agent.get_conversation('user_123')

# 导出为 JSON
agent.export_conversation('user_123', '/tmp/conversation.json')
```

## API 参考

### 存储模块

| 类 | 描述 |
|---|---|
| `DuckTable` | 通过 DuckDB 后端视图管理 Parquet 文件目录 |
| `DuckPQ` | 多 Hive 分区 Parquet 表的数据库式管理器 |

### Agent 模块

| 类/函数 | 描述 |
|---|---|
| `Agent` | 基于 openai-agents 的高级封装，支持 RAG |
| `Collection` | 基于 ChromaDB 和 OpenAI 嵌入的知识库 |
| `MCP` | 暴露 parquool 能力的 MCP 服务器封装 |
| `run_mcp()` | MCP 服务器的 CLI 入口点 |

### 工具模块

| 函数 | 描述 |
|---|---|
| `setup_logger()` | 创建带可选文件处理器的可配置日志器 |
| `notify_task()` | 任务完成时发送邮件通知的装饰器 |
| `proxy_request()` | 带代理故障转移和重试的 HTTP 请求 |
| `generate_usage()` | 为类和函数自动生成文档 |
| `google_search()` | 通过 SerpAPI 进行 Google 搜索 |
| `read_url()` | 通过 Jina reader 获取网页摘要 |

## 环境变量

| 变量 | 使用者 | 描述 |
|---|---|---|
| `OPENAI_BASE_URL` | Agent, Collection | OpenAI 兼容 API 基础 URL |
| `OPENAI_API_KEY` | Agent, Collection | API 密钥 |
| `OPENAI_MODEL_NAME` | Agent | 默认模型名称 |
| `OPENAI_EMBEDDING_MODEL` | Collection | 嵌入模型 |
| `AGENT_VECTOR_DB_PATH` | Collection | ChromaDB 持久化路径 |
| `NOTIFY_TASK_SENDER` | notify_task | 邮件发送者 |
| `NOTIFY_TASK_PASSWORD` | notify_task | 邮件密码 |
| `NOTIFY_TASK_RECEIVER` | notify_task | 邮件接收者 |
| `NOTIFY_TASK_SMTP_SERVER` | notify_task | SMTP 服务器 |
| `NOTIFY_TASK_SMTP_PORT` | notify_task | SMTP 端口 |
| `NOTIFY_TASK_CC` | notify_task | CC 接收者 |
| `SERPAPI_KEY` | google_search | SerpAPI 密钥（多个用逗号分隔）|

## 文档

- [文档索引](./docs/README.md) - 面向 AGENT 优化的文档索引
- [存储模块](./docs/storage.md) - DuckTable 和 DuckPQ 文档
- [Agent 模块](./docs/agent.md) - Agent 和 Collection 文档
- [工具模块](./docs/util.md) - 工具函数文档

## 许可证

MIT 许可证
