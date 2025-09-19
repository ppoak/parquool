# Parquool

Parquool is a lightweight Python library that makes working with Parquet datasets feel like working with a SQL table. It leverages DuckDB for fast SQL querying over parquet files and provides convenient utilities for partitioned writes, row-level upsert/update/delete operations, logging, HTTP proxy requests with retry, email task notifications, and an OpenAI Agent wrapper.

Key features
- Create a DuckDB view over a parquet dataset (parquet_scan) and query it using SQL-like methods.
- Upsert (merge) data from pandas DataFrames using primary keys, with optional partitioned output.
- Perform atomic update and delete operations that rewrite parquet directories safely.
- Helpers for pivoting (DuckDB PIVOT and pandas.pivot_table), counting and general SELECT operations that return pandas.DataFrame.
- Utilities: configurable logger (with rotation), proxy_request with retries, notify_task decorator for email notifications, and BaseAgent built on openai-agents for conversational workflows.

## Install

Install from PyPI:

```bash
pip install parquool
```

(Dependencies are declared in pyproject.toml and include duckdb, pandas, openai-agents, requests, retry, etc.)

## Quick start — DuckParquet

This demonstrates common operations: create, select, upsert, update, delete.

```python
# file: example.py
from parquool import DuckParquet
import pandas as pd

# Open (or create) a dataset directory
dp = DuckParquet('data/my_dataset')

# Query (like SELECT)
df = dp.select(columns=['id', 'value'], where='value > 10', limit=100)
print(df.head())

# Upsert: provide primary key columns
new = pd.DataFrame([{'id': 1, 'value': 42}, {'id': 2, 'value': 99}])
dp.upsert_from_df(new, keys=['id'], partition_by=['id'])

# Update: set column values using expressions or Python values
dp.update(set_map={'value': 0}, where='value < 0')

# Delete: remove rows matching condition
dp.delete(where="id = 3")
```

## Primary classes and methods

- DuckParquet(dataset_path, name=None, db_path=None, threads=None)
  - select(...): flexible query returning pandas.DataFrame; supports where, group_by, order_by, limit, distinct.
  - dpivot(...): uses DuckDB PIVOT to produce wide tables.
  - ppivot(...): uses pandas.pivot_table for wide pivoting.
  - count(where=None): row count.
  - upsert_from_df(df, keys, partition_by=None): upsert by keys, supports partitioned output.
  - update(set_map, where=None, partition_by=None): update columns and atomically replace parquet files.
  - delete(where, partition_by=None): delete rows and atomically replace parquet files.
  - refresh(): recreate the DuckDB view (call if files changed externally).

### Utilities

- setup_logger(name, level='INFO', file=None, rotation=None, ...)
  - Create a logger with optional file output and rotation (size or time).

- proxy_request(url, method='GET', proxies=None, delay=1, **kwargs)
  - Attempts requests through provided proxies in order, falls back to direct request; decorated with retry.

- notify_task(sender=None, password=None, receiver=None, smtp_server=None, smtp_port=None, cc=None)
  - A decorator that sends an email after the decorated function runs (success or failure). It formats pandas outputs as markdown, can embed local images (CID) and attach files found in markdown links. SMTP config can come from environment variables.

Note: The implementation contains a note in the source about a potential bug where smtp_port may be incorrectly assigned; please verify your SMTP configuration before use.

## BaseAgent (OpenAI agent wrapper)

BaseAgent is a convenience wrapper around openai-agents that:
- Loads OpenAI configuration from environment variables and configures a default client.
- Provides run/run_sync/run_streamed and a small interactive CLI (agent.cli()).
- Useful when you want to combine dataset operations with LLM-driven workflows.

### Example:

```python
from parquool import BaseAgent
agent = BaseAgent(name='myagent')
res = agent.run_sync('Summarize the following data...')
print(res)

# Start a simple synchronous CLI
agent.cli()
```

## Environment variables

You can store configuration in a .env file. Common variables used by the project:
- OPENAI_BASE_URL: optional base URL for an OpenAI-compatible service
- OPENAI_API_KEY: API key for OpenAI
- OPENAI_MODEL_NAME: default model name used by BaseAgent
- NOTIFY_TASK_SENDER, NOTIFY_TASK_PASSWORD, NOTIFY_TASK_RECEIVER, NOTIFY_TASK_SMTP_SERVER, NOTIFY_TASK_SMTP_PORT, NOTIFY_TASK_CC: for notify_task

## Contributing

Contributions are welcome. Please open issues or submit pull requests with clear descriptions and tests where applicable.

## License

See pyproject.toml — the project is licensed under the MIT License.

## Author

ppoak <ppoak@foxmail.com>
Homepage: https://github.com/ppoak/parquool
