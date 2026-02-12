## Class `DuckTable`

- Module: `parquool.storage`
- Qualname: `DuckTable`

### Summary
Manage a directory of Parquet files through a DuckDB-backed view.

### Description
Descriptions:
This class exposes a convenient API for querying and mutating a parquet
dataset stored in a directory. Internally it creates a DuckDB connection
(in-memory by default or a file DB if db_path is provided) and registers a
CREATE OR REPLACE VIEW over parquet_scan(...) (with Hive-style partitioning
enabled).

Notices:
    - If you pass an existing DuckDBPyConnection in `con`, the connection
      is treated as *externally owned* and `DuckTable.close()` will NOT
      close it. This is used by DuckPQ to share a single connection across
      many tables.
    - If you pass `con` as a path or leave it as None, DuckTable will
      create and own its own DuckDB connection and close it on `close()`.

### Attributes

| Name | Type | Description |
| ---- | ---- | ----------- |
| `root_path` | `str` | Directory path that stores the parquet dataset. |
| `name` | `Optional[str]` | The view name. Defaults to directory basename. |
| `create` | `bool` | If True, create the directory if it doesn't exist. |
| `con` | `Optional[Union[str, duckdb.DuckDBPyConnection]]` | Either: - DuckDB connection object (externally managed), or - Path to DuckDB database file, or - None (in-memory DB, internally managed). |
| `threads` | `Optional[int]` | Number of threads used for operations. |
| `columns` | `List[str]` | List all columns in the dataset. |
| `empty` | `bool` | Return True if the parquet path is empty. |
| `schema` | `DataFrame` | Get the schema (column info) of current parquet dataset. |

### Examples
    >>> dp = DuckTable("/path/to/parquet_dir")
    >>> df = dp.select("*", where="ds = '2025-01-01'")
    >>> dp.upsert_from_df(new_rows_df, keys=["id"], partition_by=["ds"])
    >>> dp.refresh()  # refresh the internal DuckDB view after external changes
    >>> dp.close()

### Methods

#### `close`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def close(self)
```

**Summary**

Close the DuckDB connection if it is owned by this instance.

**Returns**

- Type: `any`

#### `compact`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def compact(self, compression: str = 'zstd', max_workers: int = 8, engine: str = 'pyarrow') -> List[str]
```

**Summary**

Compact partition directories with multiple parquet files into single parquet file.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `compression` | `str` | no | `'zstd'` |  |
| `max_workers` | `int` | no | `8` |  |
| `engine` | `str` | no | `'pyarrow'` |  |

**Returns**

- Type: `List[str]`

#### `dpivot`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def dpivot(self, index: Union[str, List[str]], columns: str, values: str, aggfunc: str = 'first', where: Optional[str] = None, on_in: Optional[List[Any]] = None, group_by: Union[str, List[str], NoneType] = None, order_by: Union[str, List[str], NoneType] = None, limit: Optional[int] = None, fill_value: Any = None) -> pandas.core.frame.DataFrame
```

**Summary**

Pivot the parquet dataset using DuckDB PIVOT statement.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `index` | `str or List` | yes |  |  |
| `columns` | `str` | yes |  |  |
| `values` | `str` | yes |  |  |
| `aggfunc` | `str` | no | `'first'` |  |
| `where` | `Optional[str]` | no |  |  |
| `on_in` | `Optional[List]` | no |  |  |
| `group_by` | `str or List or NoneType` | no |  |  |
| `order_by` | `str or List or NoneType` | no |  |  |
| `limit` | `Optional[int]` | no |  |  |
| `fill_value` | `Any` | no |  |  |

**Returns**

- Type: `DataFrame`

#### `drop`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def drop(self)
```

**Summary**

Drop the underlying DuckDB view, if it exists.

**Returns**

- Type: `any`

#### `execute`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> _duckdb.DuckDBPyRelation
```

**Summary**

Execute a raw SQL query and return results as a DataFrame.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sql` | `str` | yes |  |  |
| `params` | `Optional[Sequence]` | no |  |  |

**Returns**

- Type: `DuckDBPyRelation`

#### `ppivot`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def ppivot(self, index: Union[str, List[str]], columns: Union[str, List[str]], values: Union[str, List[str], NoneType] = None, aggfunc: str = 'mean', where: Optional[str] = None, params: Optional[Sequence[Any]] = None, order_by: Union[str, List[str], NoneType] = None, limit: Optional[int] = None, fill_value: Any = None, dropna: bool = True, **kwargs) -> pandas.core.frame.DataFrame
```

**Summary**

Wide pivot using Pandas pivot_table.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `index` | `str or List` | yes |  |  |
| `columns` | `str or List` | yes |  |  |
| `values` | `str or List or NoneType` | no |  |  |
| `aggfunc` | `str` | no | `'mean'` |  |
| `where` | `Optional[str]` | no |  |  |
| `params` | `Optional[Sequence]` | no |  |  |
| `order_by` | `str or List or NoneType` | no |  |  |
| `limit` | `Optional[int]` | no |  |  |
| `fill_value` | `Any` | no |  |  |
| `dropna` | `bool` | no | `True` |  |
| `kwargs` | `any` | no |  |  |

**Returns**

- Type: `DataFrame`

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

#### `refresh`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def refresh(self)
```

**Summary**

Refresh DuckDB view after manual file changes.

**Returns**

- Type: `any`

#### `select`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def select(self, columns: Union[str, List[str]] = '*', where: Optional[str] = None, params: Optional[Sequence[Any]] = None, group_by: Union[str, List[str], NoneType] = None, having: Optional[str] = None, order_by: Union[str, List[str], NoneType] = None, limit: Optional[int] = None, offset: Optional[int] = None, distinct: bool = False) -> pandas.core.frame.DataFrame
```

**Summary**

Query current dataset with flexible SQL generated automatically.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `columns` | `str or List` | no | `'*'` |  |
| `where` | `Optional[str]` | no |  |  |
| `params` | `Optional[Sequence]` | no |  |  |
| `group_by` | `str or List or NoneType` | no |  |  |
| `having` | `Optional[str]` | no |  |  |
| `order_by` | `str or List or NoneType` | no |  |  |
| `limit` | `Optional[int]` | no |  |  |
| `offset` | `Optional[int]` | no |  |  |
| `distinct` | `bool` | no | `False` |  |

**Returns**

- Type: `DataFrame`

#### `sql`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def sql(self, sql: str, params: Optional[Sequence[Any]] = None) -> _duckdb.DuckDBPyRelation
```

**Summary**

Execute a raw SQL query and return results as a DataFrame.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sql` | `str` | yes |  |  |
| `params` | `Optional[Sequence]` | no |  |  |

**Returns**

- Type: `DuckDBPyRelation`

#### `upsert`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def upsert(self, df: pandas.core.frame.DataFrame, keys: list, partition_by: Optional[list] = None)
```

**Summary**

Upsert rows from DataFrame according to primary keys, overwrite existing rows.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `df` | `DataFrame` | yes |  |  |
| `keys` | `list` | yes |  |  |
| `partition_by` | `Optional[list]` | no |  |  |

**Returns**

- Type: `any`
