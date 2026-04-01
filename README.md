# Parquool

A lightweight Python library that provides SQL-like querying over Parquet datasets, row-level upsert operations with partitioned writes, and an Agent wrapper for openai-agents with built-in RAG support.

## Features

- **DuckDB-backed Parquet Storage**: Use DuckDB's `parquet_scan` to create views and query Parquet files as if they were database tables
- **Upsert Operations**: Merge semantics by primary keys with Hive-style partitioned writes
- **SQL-based Mutations**: Update and delete operations that atomically replace directory contents
- **Pivot Operations**: Both DuckDB PIVOT and pandas pivot_table support
- **Agent Integration**: High-level wrapper for openai-agents with RAG and session management
- **Knowledge Base**: ChromaDB-backed vector storage for embedding-based retrieval
- **Utility Functions**: Configurable logging, HTTP proxy requests, email notifications, and web search

## Installation

```bash
pip install parquool
```

Optional dependencies:
```bash
pip install "parquool[knowledge]"    # ChromaDB and embeddings
pip install "parquool[websearch]"     # SerpAPI for Google search
pip install "parquool[mcp]"           # MCP server support
```

## Quick Start

### DuckTable

Query and manage a directory of Parquet files:

```python
from parquool import DuckTable
import pandas as pd

# Open a dataset directory (created if it doesn't exist)
dt = DuckTable('/path/to/parquet_dir', name='my_data', create=True)

# Query with filtering and ordering
df = dt.select(
    columns=['id', 'value', 'date'],
    where='value > 100',
    order_by='date DESC',
    limit=50
)

# Upsert by primary keys with partitioning
new_rows = pd.DataFrame([
    {'id': 1, 'value': 42, 'date': '2024-01-01'},
    {'id': 2, 'value': 99, 'date': '2024-01-02'},
])
dt.upsert(new_rows, keys=['id'], partition_by=['date'])

# Pivot using DuckDB PIVOT
pivot_df = dt.dpivot(
    index='date',
    columns='category',
    values='sales',
    aggfunc='sum'
)

# Compact partitions
dt.compact(compression='zstd')
```

### DuckPQ

Manage multiple Parquet-backed tables:

```python
from parquool import DuckPQ

# Open database with multiple tables
db = DuckPQ(root_path='/data/warehouse')

# Auto-register all subdirectories as tables
db.register()

# Query individual tables
df = db.select(
    table='sales',
    columns=['date', 'region', 'revenue'],
    where="region = 'US'",
    limit=100
)

# Cross-table SQL joins
result = db.query("""
    SELECT s.date, s.revenue, p.product_name
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.date >= '2024-01-01'
""")
```

### Agent with RAG

```python
from parquool import Agent, Collection

# Create knowledge base
collection = Collection(
    default_collection='docs',
    embedding_model='text-embedding-3-small'
)
collection.load(['/path/to/docs'])

# Create agent with RAG
agent = Agent(
    name='assistant',
    collection=collection,
    rag_max_context=6000
)

# Run queries
result = agent.run_sync("What is our return policy?")
print(result.final_output)
```

### Streaming Output

```python
from parquool import Agent

agent = Agent(model_name='gpt-4')

# Synchronous streaming
result = agent.run_streamed_sync('Tell me a story')
```

### Session Management

```python
from parquool import Agent

agent = Agent(session_db='/tmp/sessions.db')

# Run with specific session
result1 = agent.run_sync('My name is Alice', session_id='user_123')
result2 = agent.run_sync('What is my name?', session_id='user_123')

# Get conversation history
messages = agent.get_conversation('user_123')

# Export to JSON
agent.export_conversation('user_123', '/tmp/conversation.json')
```

## API Reference

### Storage Module

| Class | Description |
|-------|-------------|
| `DuckTable` | Manages a directory of Parquet files through a DuckDB-backed view |
| `DuckPQ` | Database-like manager for multiple Hive-partitioned Parquet tables |

### Agent Module

| Class/Function | Description |
|----------------|-------------|
| `Agent` | High-level wrapper for openai-agents with RAG support |
| `Collection` | Knowledge store backed by ChromaDB and OpenAI embeddings |
| `MCP` | MCP server wrapper for exposing parquool capabilities |
| `run_mcp()` | CLI entry point for MCP server |

### Util Module

| Function | Description |
|----------|-------------|
| `setup_logger()` | Create configurable logger with optional file handlers |
| `notify_task()` | Decorator that sends email notifications on task completion |
| `proxy_request()` | HTTP requests with proxy failover and retry |
| `generate_usage()` | Auto-generate documentation for classes and functions |
| `google_search()` | Google search via SerpAPI |
| `read_url()` | Fetch and summarize web page content via Jina reader |

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `OPENAI_BASE_URL` | Agent, Collection | OpenAI-compatible API base URL |
| `OPENAI_API_KEY` | Agent, Collection | API authentication |
| `OPENAI_MODEL_NAME` | Agent | Default model name |
| `OPENAI_EMBEDDING_MODEL` | Collection | Embedding model |
| `AGENT_VECTOR_DB_PATH` | Collection | ChromaDB persistence path |
| `NOTIFY_TASK_SENDER` | notify_task | Email sender |
| `NOTIFY_TASK_PASSWORD` | notify_task | Email password |
| `NOTIFY_TASK_RECEIVER` | notify_task | Email recipient |
| `NOTIFY_TASK_SMTP_SERVER` | notify_task | SMTP server |
| `NOTIFY_TASK_SMTP_PORT` | notify_task | SMTP port |
| `NOTIFY_TASK_CC` | notify_task | CC recipients |
| `SERPAPI_KEY` | google_search | SerpAPI key(s), comma-separated |

## Documentation

- [Documentation Index](./docs/README.md) - AGENT-optimized documentation index
- [Storage Module](./docs/storage.md) - DuckTable and DuckPQ documentation
- [Agent Module](./docs/agent.md) - Agent and Collection documentation
- [Util Module](./docs/util.md) - Utility functions documentation

## License

MIT License
