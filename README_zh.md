# Parquool

Parquool（项目名：parquool）是一个轻量级的 Python 库，提供对 parquet 数据集的 SQL 式查询、分区写入、行级 upsert/update/delete 等常用数据工程操作的便捷封装，并包含一些实用的工具函数（日志、HTTP 代理请求、任务通知装饰器）以及一个基于 openai-agents 的 Agent 包装器（BaseAgent）。

该库旨在简化在本地或服务器上以 parquet 文件为数据存储时的常见数据管理场景，基于 DuckDB 提供高性能的 SQL 查询能力并支持将查询结果写回为分区 parquet 文件。

## 主要特性

- 使用 DuckDB 的 parquet_scan 创建视图，像操作数据库表一样查询 parquet 数据。
- 支持按主键的 upsert（合并）逻辑，支持分区写入（partition_by）。
- 支持基于 SQL 的 update、delete 操作，并原子性替换目录内容以保证一致性。
- 提供 pandas 友好的 select、pivot（DuckDB pivot 与 pandas pivot_table）及 count 等方法。
- 附带实用工具：可配置的 logger、带重试的 proxy_request、邮件通知任务装饰器 notify_task、以及与 openai-agents 集成的 BaseAgent。

## 安装

推荐通过 pip 安装：

```bash
pip install parquool
```

（注意：项目依赖会在 pyproject.toml 中声明，包含 duckdb、pandas、openai-agents 等）

快速开始 — DuckParquet

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

### Agent 封装 — BaseAgent

BaseAgent 基于 openai-agents 封装常见初始化逻辑并提供交互式 CLI：
- 初始化会读取环境变量（OPENAI_BASE_URL、OPENAI_API_KEY、OPENAI_MODEL_NAME 等）并配置默认 openai 客户端。
- 提供 run/run_sync/run_streamed/cli 等方法用于运行 prompt、流式输出和交互式 CLI。

简单示例：

```python parquool.py
from parquool import BaseAgent

agent = BaseAgent(name='myagent')
# 同步运行（阻塞）
res = agent.run_sync('Summarize the following data...')
print(res)

# 交互 CLI
agent.cli()
```

### 环境变量

建议在项目根目录创建 .env 文件以便于配置：

- OPENAI_BASE_URL: OpenAI 兼容服务的基础 URL（可选）
- OPENAI_API_KEY: OpenAI API key
- OPENAI_MODEL_NAME: 默认使用的模型名
- NOTIFY_TASK_*: notify_task 装饰器相关的邮件配置

## 贡献

欢迎提交 issue 和 PR。建议在 PR 中包含相关单元测试及复现步骤，以便验证对 parquet 文件替换与数据一致性相关的改动。

## 许可证

本项目在 pyproject.toml 中声明为 MIT 许可证。

## 联系方式

作者: ppoak <ppoak@foxmail.com>
项目主页: https://github.com/ppoak/parquool
