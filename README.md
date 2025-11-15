# Parquool

Parquool (project name: parquool) is a lightweight Python library that provides SQL-like querying over Parquet datasets, partitioned writes, row-level upsert/update/delete operations, and other common data engineering conveniences. It also includes several utility functions (logging, HTTP proxy requests, a task notification decorator) and an Agent wrapper built on openai-agents, together with a companion Collection tool for knowledge-base management.

The library aims to simplify common data management scenarios when using Parquet files as storage locally or on servers. It leverages DuckDB for high-performance SQL queries and supports writing query results back as partitioned Parquet files. The Agent class offers a convenient, out-of-the-box interface to openai-agents. Collection provides an easy-to-use toolset to embed a knowledge base into a vector database for LLM access.

## Key Features

- Use DuckDB's parquet_scan to create views and query Parquet files as if they were database tables.
- Support upsert (merge) semantics by primary keys and support partitioned writes (partition_by).
- Support SQL-based update and delete operations and atomically replace directory contents to ensure consistency.
- Provide pandas-friendly select, pivot (DuckDB PIVOT and pandas pivot_table) and count utilities.
- Includes practical utilities: a configurable logger, proxy_request with retries, and a notify_task decorator for email notifications.
- Agent integration with openai-agents: easy agent initialization and usage out of the box.
- Knowledge-base management backed by chromadb for vector embeddings — convenient for embedding content to be used by Agents.

## Installation

Install via pip (recommended):

```bash
pip install parquool
```

If you want knowledge-base integration:

```bash
pip install "parquool[knowledge]"
```

If you want web search integration:

```bash
pip install "parquool[websearch]"
```

## Quick Start

### DuckParquet

Below is a common usage scenario: create a DuckParquet instance, then query, upsert, update and delete data.

```python
from parquool import DuckParquet
import pandas as pd

# Open a dataset directory (created if it doesn't exist)
dp = DuckParquet('data/my_dataset')

# Query (equivalent to SELECT * FROM view)
df = dp.select(columns=['id', 'value'], where='value > 10', limit=100)
print(df.head())

# upsert: insert or update (requires specifying primary keys)
new = pd.DataFrame([{'id': 1, 'value': 42}, {'id': 2, 'value': 99}])
dp.upsert_from_df(new, keys=['id'], partition_by=['id'])

# update: update column values by condition
dp.update(set_map={'value': 0}, where='value < 0')

# delete: remove rows matching condition
dp.delete(where="id = 3")
```

#### Main Classes and Methods Overview

- DuckParquet(dataset_path, name=None, db_path=None, threads=None)
  - select(...): General query interface supporting where, group_by, order_by, limit, distinct, etc.
  - dpivot(...): Use DuckDB's PIVOT syntax to pivot to a wide table.
  - ppivot(...): Use pandas.pivot_table to pivot.
  - count(where=None): Count rows.
  - upsert_from_df(df, keys, partition_by=None): Upsert by keys, supports partitioning.
  - update(set_map, where=None, partition_by=None): Update columns based on SQL expressions or values and overwrite Parquet files.
  - delete(where, partition_by=None): Delete rows matching where and overwrite Parquet files.
  - refresh(): Recreate or replace the DuckDB view (call after manual file changes).

### Utilities

- setup_logger(name, level='INFO', file=None, rotation=None, ...)
  - Quickly create a logger with an optional file handler (supports rotation by size or by time).
- proxy_request(url, method='GET', proxies=None, delay=1, **kwargs)
  - Performs HTTP requests with retries (via a retry decorator) and tries provided proxies in order, falling back to a direct connection.
- notify_task(sender=None, password=None, receiver=None, smtp_server=None, smtp_port=None, cc=None)
  - A function decorator that sends an email notification on task success or failure. Supports converting pandas.DataFrame/Series to markdown and embedding local images (CID) or attachments in the markdown.
  - Configuration can also be provided via environment variables: NOTIFY_TASK_SENDER, NOTIFY_TASK_PASSWORD, NOTIFY_TASK_RECEIVER, NOTIFY_TASK_SMTP_SERVER, NOTIFY_TASK_SMTP_PORT, NOTIFY_TASK_CC.
  - Note: There is a comment in the source mentioning smtp_port may be assigned incorrectly — please verify configuration before use.
- generate_usage(target: object, output_path: Optional[str] = None, *, include_private: bool = False, include_inherited: bool = False, include_properties: bool = True, include_methods: bool = True, method_kinds: tuple[str, ...] = ("instance", "class", "static"), method_include: Optional[list[str]] = None, method_exclude: Optional[list[str]] = None, attribute_include: Optional[list[str]] = None, attribute_exclude: Optional[list[str]] = None, sort_methods: Literal["name", "kind", "none"] = "name", render_tables: bool = True, include_signature: bool = True, include_sections: Optional[Literal["summary", "description", "attributes", "methods", "parameters", "returns", "raises", "examples",]] = None, heading_level: int = 2 ) -> str
  - Automatically generate usage documentation for a given class or function with many options for fine-grained control.
- google_search(query: str, location: Literal["China", "United States", "Germany", "France"] = None, country: str = None, language: str = None, to_be_searched: str = None, start: str = None, num: str = None)
  - Google search function: pass keywords and search parameters to receive aggregated results.
- read_url(url_or_urls: Union[str, List], engine: Literal["direct", "browser"] = None, return_format: Literal["markdown", "html", "text", "screeshot"] = None, with_links_summary: Literal["all", "true"] = "true", with_image_summary: Literal["all", "true"] = "true", retain_image: bool = False, do_not_track: bool = True, set_cookie: str = None, max_length_each: int = 100000)
  - A page reader that converts web pages into LLM-friendly markdown via a Jina interface.

### Agent Wrapper — Agent

Parquool wraps common initialization logic for openai-agents:

- Initialization reads environment variables (OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL_NAME, etc.) and configures a default litellm client.
- Provides run/run_sync/run_streamed/cli methods to run prompts, stream outputs, and interact via CLI.

Simple example:

```python
from parquool import Agent
agent = Agent(name='myagent')

# synchronous run (blocking)
res = agent.run_sync('Summarize the following data...')
# synchronous run with streaming
res = agent.run_streamd_sync('Hi')
print(res)
```

- run/run_sync return a RunResult object from openai_agents; use res.final_output to get the final output string.
- run_streamed/run_stream_sync return a list of dicts representing dialog items, including context, role, etc.
- You can also use agent.get_all_conversations to get all conversation session_ids, agent.get_conversation(session_id) to retrieve conversation data for a session, and agent.export_conversation to save a session to JSON.

Using Collection for knowledge-base backed search:

```python
from parquool import Collection
collection = Collection()
collection.load(["myfile.txt", "myfile.md"])
# ... load more files once
agent = Agent(collection=collection)
agent.run_streamed_sync("What's my plan for tomorrow?")
```

Streamlit visualization of an agent (install streamlit first via pip). To add the search tool, configure SERPAPI_KEY in environment variables.

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

### Environment Variables

It is recommended to create a .env file in your project root for configuration:

- OPENAI_BASE_URL: Base URL for OpenAI-compatible services (optional)
- OPENAI_API_KEY: OpenAI API key
- OPENAI_MODEL_NAME: Default model name to use
- NOTIFY_TASK_*: Configuration for the notify_task decorator

## Contributing

Issues and PRs are welcome. Please include unit tests and reproduction steps in PRs, especially for changes related to atomic Parquet file replacement and data consistency.

## License

This project is declared under the MIT License in pyproject.toml.

## Contact

Author: ppoak <ppoak@foxmail.com>
Project: https://github.com/ppoak/parquool
