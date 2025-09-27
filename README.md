# Parquool

Parquool (package name: parquool) is a lightweight Python library that provides SQL-like querying for parquet datasets, partitioned writes, row-level upsert/update/delete operations, and other convenient data engineering helpers. It also includes some utility functions (logging, HTTP proxy requests, a task notification decorator) and an Agent wrapper built on openai-agents, together with a companion knowledge management tool called Collection.

The library aims to simplify common data management scenarios when using parquet files as storage locally or on a server. It uses DuckDB for high-performance SQL queries and supports writing query results back as partitioned parquet files. The Agent class provides a convenient, out-of-the-box interface to openai-agents. Collection offers an easy-to-use knowledge management tool that helps users quickly embed knowledge into a vector database for LLM access.

## Key Features

- Create DuckDB views with parquet_scan to query parquet data as if they were database tables.
- Support upsert (merge) semantics based on primary keys, with optional partitioned writes (partition_by).
- Support SQL-based update and delete operations and atomically replace directory contents to guarantee consistency.
- Provide pandas-friendly select, pivot (DuckDB pivot and pandas pivot_table) and count methods.
- Includes utilities: configurable logger, proxy_request with retry, and notify_task email notification decorator.
- Agent wrapper integrated with openai-agents for easy agent creation and usage.
- Knowledge management based on chromadb for vector store integration — useful for embedding content for Agents.

## Installation

We recommend installing via pip:

```bash
pip install parquool
```

For knowledge integration, install:

```bash
pip install "parquool[knowledge]"
```

For web search tool integration, install:

```bash
pip install "parquool[websearch]"
```

## Quick Start — DuckParquet

Below is a demonstration of common usage: creating a DuckParquet instance, querying, upserting, updating and deleting.

```python parquool.py
from parquool import DuckParquet
import pandas as pd

# Open a directory (created if it does not exist)
dp = DuckParquet('data/my_dataset')

# Query (equivalent to SELECT * FROM view)
df = dp.select(columns=['id', 'value'], where='value > 10', limit=100)
print(df.head())

# upsert: insert or update (must provide primary key columns)
new = pd.DataFrame([{'id': 1, 'value': 42}, {'id': 2, 'value': 99}])
dp.upsert_from_df(new, keys=['id'], partition_by=['id'])

# update: update column values by condition
dp.update(set_map={'value': 0}, where='value < 0')

# delete: remove rows matching the condition
dp.delete(where="id = 3")
```

## Main Classes and Methods Overview

- DuckParquet(dataset_path, name=None, db_path=None, threads=None)
  - select(...): General query interface supporting where, group_by, order_by, limit, distinct, etc.
  - dpivot(...): Perform wide-table pivot using DuckDB's PIVOT syntax.
  - ppivot(...): Perform pivot using pandas.pivot_table.
  - count(where=None): Count rows.
  - upsert_from_df(df, keys, partition_by=None): Upsert by keys, supports partitioning.
  - update(set_map, where=None, partition_by=None): Update columns using SQL expressions or values and overwrite the parquet directory.
  - delete(where, partition_by=None): Delete rows matching where and overwrite the parquet directory.
  - refresh(): Recreate or replace the DuckDB view (call after manual file changes).

### Utilities

- setup_logger(name, level='INFO', file=None, rotation=None, ...)
  - Quickly create a logger with optional file handler (supports rotation by size or time).

- proxy_request(url, method='GET', proxies=None, delay=1, **kwargs)
  - HTTP request helper with retry support; tries provided proxies in order and falls back to direct connection.

- notify_task(sender=None, password=None, receiver=None, smtp_server=None, smtp_port=None, cc=None)
  - A function decorator that sends an email notification after a task succeeds or fails. It supports converting pandas.DataFrame/Series to Markdown; can embed local images (CID) or attach files in the Markdown content.
  - Configurable through environment variables: NOTIFY_TASK_SENDER, NOTIFY_TASK_PASSWORD, NOTIFY_TASK_RECEIVER, NOTIFY_TASK_SMTP_SERVER, NOTIFY_TASK_SMTP_PORT, NOTIFY_TASK_CC.
  - Note: There is a remark in the source code indicating smtp_port may be assigned incorrectly — please verify configuration before use.

### Agent Wrapper — Agent

BaseAgent wraps openai-agents with common initialization logic:
- It reads environment variables (LITELLM_BASE_URL, LITELLM_API_KEY, LITELLM_MODEL_NAME, etc.) and configures a default litellm client.
- Provides run/run_sync/run_streamed/cli methods for executing prompts, streaming output, and interactive CLI.

Simple example:

```python
from parquool import Agent

agent = Agent(name='myagent')
# Synchronous run (blocking)
res = agent.run_sync('Summarize the following data...')
print(res)
```

Use Collection to link a knowledge collection and enable knowledge search:

```python
from parquool import Collection

collection = Collection()
collection.load(["myfile.txt", "myfile.md"])
... # more files can be loaded; this usually only needs to be done once
agent = Agent(collection=collection)
agent.run_streamed_sync("What's my plan for tomorrow?")
```

You can visualize the agent with Streamlit. Install streamlit first via pip. If you want to add a web search tool, set up a SERPAPI key by adding SERPAPI_KEY to your environment variables.

Example Streamlit usage:

```python
import streamlit as st
from parquool import Agent
from openai.types.responses import ResponseTextDeltaEvent


async def stream(prompt):
    async for event in st.session_state.agent.stream(prompt):
        # Print streaming delta if available
        if event.type == "raw_response_event" and isinstance(
            event.data, ResponseTextDeltaEvent
        ):
            yield event.data.delta
        elif event.type == "run_item_stream_event":
            if event.item.type == "tool_call_item":
                yield f"{event.item.raw_item.name} - {event.item.raw_item.arguments}\n\n"
            elif event.item.type == "tool_call_output_item":
                yield event.item.output
            else:
                pass


st.title("Test Agent")

if not st.session_state.get("agent"):
    st.session_state.agent = Agent(
        tools=[Agent.google_search, Agent.read_url]
    )

st.session_state.messages = st.session_state.agent.get_conversation()

for message in st.session_state.messages:
    if message.get("role") == "user":
        with st.chat_message("user"):
            st.markdown(message["content"])
    elif message.get("role") == "assistant":
        with st.chat_message("assistant"):
            st.markdown(message["content"][0]["text"])
    elif message.get("type") == "function_call":
        with st.chat_message("assistant"):
            with st.expander(message["name"]):
                st.code(message["arguments"])
    elif message.get("type") == "function_call_output":
        with st.chat_message("assistant"):
            with st.expander("Expand to see the result"):
                st.code(message["output"])

if prompt := st.chat_input("What's up?"):
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        response = st.write_stream(stream(prompt))
```

## Environment Variables

It is recommended to create a .env file in the project root for configuration:

- LITELLM_BASE_URL: Base URL for an OpenAI-compatible service (optional)
- LITELLM_API_KEY: OpenAI API key
- LITELLM_MODEL_NAME: Default model name to use
- NOTIFY_TASK_*: Configuration for the notify_task decorator (see above)

## Contributing

Issues and pull requests are welcome. When submitting a PR, please include related unit tests and reproduction steps where applicable, especially for changes that touch parquet file replacement and data consistency.

## License

This project is declared under the MIT License in pyproject.toml.

## Contact

Author: ppoak <ppoak@foxmail.com>  
Project homepage: https://github.com/ppoak/parquool