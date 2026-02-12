## Class `DuckPQ`

- Module: `parquool.storage`
- Qualname: `DuckPQ`

### Summary
Database-like manager for a directory of Hive-partitioned Parquet tables.

### Description
DuckPQ wraps a single DuckDB connection and a set of Parquet-backed tables
(one directory per table) under a common root directory. Each table
directory is handled by a DuckTable instance, and a DuckDB VIEW is
created for each table name, so you can query them using SQL on the shared
DuckDB connection.

### Attributes

| Name | Type | Description |
| ---- | ---- | ----------- |
| `root_path` | `` | Root directory for the Parquet database. Each immediate subdirectory is treated as a table. |
| `database` | `` | DuckDB database spec: - DuckDBPyConnection instance: reuse this connection (DuckPQ will not close it). - String path: DuckDB file path, will call duckdb.connect. - None: use in-memory DuckDB (":memory:"). |
| `config` | `` | Extra DuckDB connection config, merged into duckdb.connect. |
| `threads` | `` | Number of DuckDB threads to set via "SET threads=...". |

### Examples
    >>> db = DuckPQ(root_dir="database", database="duckpq.duckdb", threads=4)
    # tables and schema are auto-discovered
    >>> db.tables.keys()
    dict_keys(["quotes_min", "tick_level2", ...])
    # Upsert into a table (creates directory if missing)
    >>> db.upsert(
    ...     table="quotes_min",
    ...     df=df_quotes,
    ...     keys=["symbol", "ts"],
    ...     partition_by=["trade_date"],
    ... )
    # Table select via DuckTable
    >>> df = db.select(
    ...     table="quotes_min",
    ...     columns="*",
    ...     where="trade_date = '2025-01-02'",
    ... )
    # Arbitrary SQL on the shared DuckDB connection (cross-table joins, etc.)
    >>> join_df = db.execute(
    ...     '''
    ...     SELECT *
    ...     FROM quotes_min q
    ...     JOIN tick_level2 t
    ...       ON q.symbol = t.symbol AND q.ts = t.ts
    ...     WHERE q.trade_date = '2025-01-02'
    ...     '''
    ... )

### Methods

#### `attach`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def attach(self, name: str, df: pandas.core.frame.DataFrame, replace: bool = True, materialize: bool = False) -> None
```

**Summary**

Register a pandas DataFrame as a DuckDB relation.

**Description**

This method exposes a pandas DataFrame to the underlying DuckDB
connection, allowing it to be queried using SQL. Depending on
`materialize`, the DataFrame can be registered as:

- a DuckDB view / relation (via `con.register`), or
- a temporary DuckDB table (via `CREATE TEMP TABLE AS`).

The registered object lives within the lifetime of the DuckDB
connection and does not persist to disk unless explicitly copied
out later.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `name` | `str` | yes |  | Name of the DuckDB view or table to register. |
| `df` | `DataFrame` | yes |  | pandas DataFrame to expose to DuckDB. |
| `replace` | `bool` | no | `True` | Whether to drop an existing view or table with the same name before registration. |
| `materialize` | `bool` | no | `False` | If True, create a temporary DuckDB table instead of a view / relation. |

**Returns**

- Type: `None`
- Description: None

#### `close`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def close(self) -> None
```

**Summary**

Close the underlying DuckDB connection if owned by DuckPQ.

**Description**

After calling close(), the DuckPQ instance should not be used for
further operations.

**Returns**

- Type: `None`

#### `compact`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def compact(self, table: str, compression: str = 'zstd', max_workers: int = 8, engine: str = 'pyarrow') -> List[str]
```

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `table` | `str` | yes |  |  |
| `compression` | `str` | no | `'zstd'` |  |
| `max_workers` | `int` | no | `8` |  |
| `engine` | `str` | no | `'pyarrow'` |  |

**Returns**

- Type: `List[str]`

#### `execute`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> _duckdb.DuckDBPyRelation
```

**Summary**

Execute arbitrary SQL on the shared DuckDB connection.

**Description**

This method operates at the connection level, so it can query multiple
tables, perform joins, aggregations, create regular DuckDB tables or
views, etc. Parquet-backed tables appear as normal views (by table
name) inside this connection.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sql` | `str` | yes |  | SQL statement to execute. |
| `params` | `Optional[Sequence]` | no |  | Optional sequence of bind parameters. |

**Returns**

- Type: `DuckDBPyRelation`
- Description: the DuckDB relation.

#### `query`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pandas.core.frame.DataFrame
```

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sql` | `str` | yes |  |  |
| `params` | `Optional[Sequence]` | no |  |  |

**Returns**

- Type: `DataFrame`

#### `register`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def register(self, name: Optional[str] = None) -> None
```

**Summary**

Register table directories under root_dir and attach them.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `name` | `Optional[str]` | no |  |  |

**Returns**

- Type: `None`

#### `registrable`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def registrable(self)
```

**Summary**

Registrable table under root path

**Returns**

- Type: `any`

#### `select`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def select(self, table: str, columns: Union[str, List[str]] = '*', where: Optional[str] = None, params: Optional[Sequence[Any]] = None, group_by: Union[str, List[str], NoneType] = None, having: Optional[str] = None, order_by: Union[str, List[str], NoneType] = None, limit: Optional[int] = None, offset: Optional[int] = None, distinct: bool = False) -> pandas.core.frame.DataFrame
```

**Summary**

Select from a Parquet-backed table via DuckTable.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `table` | `str` | yes |  | Table name to query. |
| `columns` | `str or List` | no | `'*'` | Column list or "*" for all columns. |
| `where` | `Optional[str]` | no |  | Optional WHERE clause string. |
| `params` | `Optional[Sequence]` | no |  | Optional sequence of bind parameters for WHERE. |
| `group_by` | `str or List or NoneType` | no |  | Optional GROUP BY columns or expression. |
| `having` | `Optional[str]` | no |  | Optional HAVING clause. |
| `order_by` | `str or List or NoneType` | no |  | Optional ORDER BY columns or expression. |
| `limit` | `Optional[int]` | no |  | Optional row limit. |
| `offset` | `Optional[int]` | no |  | Optional row offset. |
| `distinct` | `bool` | no | `False` | Whether to select DISTINCT. |

**Returns**

- Type: `DataFrame`
- Description: pandas.DataFrame with query results.

#### `sql`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def sql(self, sql: str, params: Optional[Sequence[Any]] = None) -> _duckdb.DuckDBPyRelation
```

**Summary**

Execute arbitrary SQL on the shared DuckDB connection.

**Description**

This method operates at the connection level, so it can query multiple
tables, perform joins, aggregations, create regular DuckDB tables or
views, etc. Parquet-backed tables appear as normal views (by table
name) inside this connection.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sql` | `str` | yes |  | SQL statement to execute. |
| `params` | `Optional[Sequence]` | no |  | Optional sequence of bind parameters. |

**Returns**

- Type: `DuckDBPyRelation`
- Description: the DuckDB relation.

#### `upsert`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def upsert(self, table: str, df: pandas.core.frame.DataFrame, keys: List[str], partition_by: Optional[List[str]] = None) -> None
```

**Summary**

Upsert rows from a DataFrame into a Parquet-backed table.

**Description**

This will create the table directory under root_dir if it does not
exist yet. Internally it delegates to DuckTable.upsert_from_df.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `table` | `str` | yes |  | Logical table name (directory name and view name). |
| `df` | `DataFrame` | yes |  | Input pandas DataFrame to upsert. |
| `keys` | `List[str]` | yes |  | Primary key column names used to deduplicate and upsert. |
| `partition_by` | `Optional[List]` | no |  | Optional list of partition columns used to create Hive-style partitions under the table directory. |

**Returns**

- Type: `None`
