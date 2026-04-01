# Parquool Documentation Index

This directory contains comprehensive documentation for the Parquool library, designed specifically for AI agents and LLM-powered applications.

## Quick Reference for Agents

### Core Modules

| Module | Description | Key Classes/Functions |
|--------|-------------|----------------------|
| [`storage`](./storage.md) | DuckDB-backed Parquet storage with SQL-like querying | `DuckTable`, `DuckPQ` |
| [`agent`](./agent.md) | Agent wrapper for openai-agents with RAG support | `Agent`, `Collection`, `MCP` |
| [`util`](./util.md) | Utility functions for logging, notifications, HTTP requests | `setup_logger`, `notify_task`, `proxy_request`, `generate_usage`, `google_search`, `read_url` |

### Public API (re-exported from `parquool`)

```python
from parquool import DuckTable, DuckPQ
from parquool import setup_logger, notify_task, proxy_request, generate_usage
from parquool import google_search, read_url
from parquool import Agent, Collection, MCP, run_mcp
```

### Agent-Optimized Resources

#### MCP Server Resources

The MCP server (`parquool.agent.MCP`) exposes auto-generated documentation via `auto-doc://` resources:

- `auto-doc://agent` - Full Agent class documentation
- `auto-doc://collection` - Full Collection class documentation
- `auto-doc://duckpq` - Full DuckPQ class documentation
- `auto-doc://ducktable` - Full DuckTable class documentation
- `auto-doc://generate_usage` - Documentation generator usage
- `auto-doc://google_search` - Web search tool documentation
- `auto-doc://notify_task` - Email notification decorator documentation
- `auto-doc://proxy_request` - HTTP proxy request documentation
- `auto-doc://read_url` - URL reader documentation
- `auto-doc://setup_logger` - Logger setup documentation

#### Tool Functions for Agents

The following functions can be directly used as tools in agent workflows:

- **`google_search(query, ...)`** - Perform Google searches via SerpAPI
- **`read_url(url_or_urls, ...)`** - Fetch and summarize web page content
- **`Agent.google_search`** - Static method, exposes web search as an agent tool
- **`Agent.read_url`** - Static method, exposes URL reading as an agent tool

#### RAG (Retrieval-Augmented Generation) Setup

```python
from parquool import Collection, Agent

# Create a knowledge base collection
collection = Collection(
    default_collection="my_knowledge",
    embedding_model="text-embedding-3-small",
    vector_db_path=".knowledge"
)

# Load documents into the collection
collection.load(["/path/to/docs"])

# Create agent with RAG capabilities
agent = Agent(collection=collection)

# Agent will automatically use knowledge base for relevant queries
result = agent.run_sync("What is in my knowledge base?")
```

### Common Patterns

#### Querying Parquet Data

```python
from parquool import DuckPQ

# Open a database of Parquet tables
db = DuckPQ(root_path="/data/tables")

# Query a table
df = db.select(
    table="sales",
    columns=["date", "region", "revenue"],
    where="revenue > 1000",
    order_by="date DESC",
    limit=100
)

# Execute arbitrary SQL across tables
result = db.query("""
    SELECT a.*, b.metadata
    FROM sales a
    JOIN products b ON a.product_id = b.id
    WHERE a.date >= '2024-01-01'
""")
```

#### Upsert with Partitioning

```python
from parquool import DuckTable
import pandas as pd

dt = DuckTable("/data/sales", name="sales")

new_data = pd.DataFrame([
    {"date": "2024-01-01", "region": "US", "revenue": 5000},
    {"date": "2024-01-02", "region": "EU", "revenue": 3000},
])

# Upsert by primary keys with Hive-style partitioning
dt.upsert(new_data, keys=["date", "region"], partition_by=["region"])
```

#### Logging Setup

```python
from parquool import setup_logger

logger = setup_logger(
    "my_app",
    level="INFO",
    file="/var/log/my_app.log",
    rotation="size",
    max_bytes=10*1024*1024,  # 10MB
    backup_count=5
)
logger.info("Application started")
```

#### Email Notifications

```python
from parquool import notify_task

@notify_task(
    sender="app@example.com",
    receiver="admin@example.com",
    smtp_server="smtp.example.com",
    smtp_port=587
)
def daily_report():
    # Generate report...
    return {"status": "success", "records_processed": 1000}
```

### Environment Variables

| Variable | Used By | Purpose |
|----------|---------|---------|
| `OPENAI_BASE_URL` | Agent, Collection | OpenAI-compatible API base URL |
| `OPENAI_API_KEY` | Agent, Collection | API authentication |
| `OPENAI_MODEL_NAME` | Agent | Default model name |
| `OPENAI_EMBEDDING_MODEL` | Collection | Embedding model |
| `AGENT_VECTOR_DB_PATH` | Collection | ChromaDB storage path |
| `NOTIFY_TASK_SENDER` | notify_task | Email sender |
| `NOTIFY_TASK_PASSWORD` | notify_task | Email password |
| `NOTIFY_TASK_RECEIVER` | notify_task | Email recipient |
| `NOTIFY_TASK_SMTP_SERVER` | notify_task | SMTP server |
| `NOTIFY_TASK_SMTP_PORT` | notify_task | SMTP port |
| `NOTIFY_TASK_CC` | notify_task | CC recipients |
| `SERPAPI_KEY` | google_search | SerpAPI key(s), comma-separated for multiple keys |

### MCP Server Usage

Start the MCP server to expose parquool capabilities to external agents:

```bash
# Default stdio transport
parquool-mcp

# SSE transport
parquool-mcp --transport sse
```

Or programmatically:

```python
from parquool.agent import MCP

server = MCP(name="parquool", instructions="Parquool data and tools server")
server.run(transport="stdio")
```

### Documentation by Topic

- [**Storage Module**](./storage.md) - Parquet data management with DuckDB
- [**Agent Module**](./agent.md) - LLM agent wrapper and knowledge base
- [**Util Module**](./util.md) - Logging, notifications, HTTP utilities
