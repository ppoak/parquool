# Parquool

Parquool（项目名：parquool）是一个轻量级的 Python 库，提供对 parquet 数据集的 SQL 式查询、分区写入、行级 upsert/update/delete 等常用数据工程操作的便捷封装，并包含一些实用的工具函数（日志、HTTP 代理请求、任务通知装饰器）以及一个基于 openai-agents 的 Agent 包装器，与之配套的一个知识库管理工具 Collection 。

该库旨在简化在本地或服务器上以 parquet 文件为数据存储时的常见数据管理场景，基于 DuckDB 提供高性能的 SQL 查询能力并支持将查询结果写回为分区 parquet 文件。 Agent 类提供了一套更为便捷操作、开箱即用的openai-agents接口。 Collection 提供了更为方便的知识库管理工具，能帮助用户最快的将知识库嵌入为向量数据库，方便 LLM 查询访问。

## 主要特性

- 使用 DuckDB 的 parquet_scan 创建视图，像操作数据库表一样查询 parquet 数据。
- 支持按主键的 upsert（合并）逻辑，支持分区写入（partition_by）。
- 支持基于 SQL 的 update、delete 操作，并原子性替换目录内容以保证一致性。
- 提供 pandas 友好的 select、pivot（DuckDB pivot 与 pandas pivot_table）及 count 等方法。
- 附带实用工具：可配置的 logger、带重试的 proxy_request、邮件通知任务装饰器 notify_task。
- Openai Agents 集成的 Agent 类，方便用户定义自己的 Agent ，开箱即用。
- 基于 chromadb 的向量知识库管理。方便嵌入 Agent 供用户创建自己的知识库内容。

## 安装

推荐通过 pip 安装：

```bash
pip install parquool
```

如果需要知识库集成，使用：

```bash
pip install "parquool[knowledge]"
```

如果需要集成搜索工具，使用：

```bash
pip install "parquool[websearch]"
```


## 快速开始 — DuckParquet

下面演示最常见的使用场景：创建 DuckParquet，查询、upsert、update 和 delete。

```python parquool.py
from parquool import DuckParquet
import pandas as pd

# 打开一个目录（若不存在则会创建）
dp = DuckParquet('data/my_dataset')

# 查询（等同于 SELECT * FROM view）
df = dp.select(columns=['id', 'value'], where='value > 10', limit=100)
print(df.head())

# upsert：插入或更新（须提供主键列表）
new = pd.DataFrame([{'id': 1, 'value': 42}, {'id': 2, 'value': 99}])
dp.upsert_from_df(new, keys=['id'], partition_by=['id'])

# update：按条件更新列值
dp.update(set_map={'value': 0}, where='value < 0')

# delete：删除满足条件的行
dp.delete(where="id = 3")
```

## 主要类与方法概览

- DuckParquet(dataset_path, name=None, db_path=None, threads=None)
  - select(...): 通用查询接口，支持 where, group_by, order_by, limit, distinct 等。
  - dpivot(...): 使用 DuckDB 的 PIVOT 语法进行宽表透视。
  - ppivot(...): 使用 pandas.pivot_table 进行透视。
  - count(where=None): 计数。
  - upsert_from_df(df, keys, partition_by=None): 按 keys 做 upsert，支持分区。
  - update(set_map, where=None, partition_by=None): 基于 SQL 表达式或值更新列并覆盖 parquet 文件目录。
  - delete(where, partition_by=None): 删除满足 where 的行并覆盖 parquet 文件目录。
  - refresh(): 重新创建或替换 DuckDB 视图（在手动修改文件后调用）。

### 实用工具

- setup_logger(name, level='INFO', file=None, rotation=None, ...)
  - 快速创建带可选 file handler（支持按大小或按时间轮替）的 Logger。

- proxy_request(url, method='GET', proxies=None, delay=1, **kwargs)
  - 带重试（通过 retry 装饰器）并按顺序尝试提供的代理列表，最后回退到直连的 HTTP 请求。

- notify_task(sender=None, password=None, receiver=None, smtp_server=None, smtp_port=None, cc=None)
  - 一个函数装饰器：在任务执行成功或失败后发送邮件通知。支持将 pandas.DataFrame/Series 转为 markdown 格式；能在 markdown 中嵌入本地图片（CID）或附件。
  - 可通过环境变量配置：NOTIFY_TASK_SENDER、NOTIFY_TASK_PASSWORD、NOTIFY_TASK_RECEIVER、NOTIFY_TASK_SMTP_SERVER、NOTIFY_TASK_SMTP_PORT、NOTIFY_TASK_CC。
  - 注意：源码中有一处备注提到 smtp_port 可能被错误赋值，使用前请验证配置。

### Agent 封装 — Agent

BaseAgent 基于 openai-agents 封装常见初始化逻辑：
- 初始化会读取环境变量（LITELLM_BASE_URL、LITELLM_API_KEY、LITELLM_MODEL_NAME 等）并配置默认 litellm 客户端。
- 提供 run/run_sync/run_streamed/cli 等方法用于运行 prompt、流式输出和交互式 CLI。

简单示例：

```python
from parquool import Agent

agent = Agent(name='myagent')
# 同步运行（阻塞）
res = agent.run_sync('Summarize the following data...')
print(res)
```

使用 Collection 知识库关联知识库内容搜索

```python
from parquool import Collection

collection = Collection()
collection.load(["myfile.txt", "myfile.md"])
... # more files can be loaded and this only need to be loaded once
agent = Agent(collection=collection)
agent.run_streamed_sync("What's my plan for tommorrow?")
```

使用 streamlit 可视化 agent，需要通过 `pip install streamlit` 先安装好streamlit。如需添加搜索工具，需要设定好serpapi的token，在环境变量配置中添加 SERPAPI_KEY 。

```python
import streamlit as st
from parquool import Agent
from openai.types.responses import ResponseTextDeltaEvent


async def stream(prompt):
    async for event in st.session_state.agent.stream(prompt):
        # We'll print streaming delta if available
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

### 环境变量

建议在项目根目录创建 .env 文件以便于配置：

- LITELLM_BASE_URL: OpenAI 兼容服务的基础 URL（可选）
- LITELLM_API_KEY: OpenAI API key
- LITELLM_MODEL_NAME: 默认使用的模型名
- NOTIFY_TASK_*: notify_task 装饰器相关的邮件配置

## 贡献

欢迎提交 issue 和 PR。建议在 PR 中包含相关单元测试及复现步骤，以便验证对 parquet 文件替换与数据一致性相关的改动。

## 许可证

本项目在 pyproject.toml 中声明为 MIT 许可证。

## 联系方式

作者: ppoak <ppoak@foxmail.com>
项目主页: https://github.com/ppoak/parquool
