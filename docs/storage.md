# Storage Module

The storage module provides DuckDB-backed Parquet storage with SQL-like querying capabilities, row-level upsert/update/delete operations, and Hive-style partitioned writes.

## Classes

### DuckTable

Manages a directory of Parquet files through a DuckDB-backed view.

```python
from parquool import DuckTable
```

#### Constructor

```python
DuckTable(
    root_path: str,
    name: Optional[str] = None,
    create: bool = False,
    database: Optional[Union[str, duckdb.DuckDBPyConnection]] = None,
    threads: Optional[int] = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `root_path` | `str` | Directory path that stores the parquet dataset |
| `name` | `Optional[str]` | The view name. Defaults to directory basename |
| `create` | `bool` | If True, create the directory if it doesn't exist |
| `database` | `Optional[Union[str, duckdb.DuckDBPyConnection]]` | DuckDB connection (externally managed), path to DuckDB database file, or None for in-memory |
| `threads` | `Optional[int]` | Number of threads used for operations |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `empty` | `bool` | True if the parquet path contains no parquet files |
| `schema` | `pd.DataFrame` | Column info (names, types) of the dataset |
| `columns` | `List[str]` | List of all column names in the dataset |

#### Methods

##### `select()`

Query the parquet dataset with flexible SQL generation.

```python
def select(
    self,
    columns: Union[str, List[str]] = "*",
    where: Optional[str] = None,
    params: Optional[Sequence[Any]] = None,
    group_by: Optional[Union[str, List[str]]] = None,
    having: Optional[str] = None,
    order_by: Optional[Union[str, List[str]]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    distinct: bool = False,
) -> pd.DataFrame
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `columns` | `Union[str, List[str]]` | Column list or "*" for all columns |
| `where` | `Optional[str]` | WHERE clause string |
| `params` | `Optional[Sequence[Any]]` | Bind parameters for WHERE clause |
| `group_by` | `Optional[Union[str, List[str]]]` | GROUP BY columns or expression |
| `having` | `Optional[str]` | HAVING clause |
| `order_by` | `Optional[Union[str, List[str]]]` | ORDER BY columns or expression |
| `limit` | `Optional[int]` | Row limit |
| `offset` | `Optional[int]` | Row offset |
| `distinct` | `bool` | Whether to select DISTINCT rows |

**Returns:** `pd.DataFrame` with query results

##### `query()`

Execute a raw SQL query and return results as a pandas DataFrame.

```python
def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame
```

##### `execute()`

Execute a raw SQL query and return results as a DuckDB relation.

```python
def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> duckdb.DuckDBPyRelation
```

##### `dpivot()`

Pivot the parquet dataset using DuckDB PIVOT statement.

```python
def dpivot(
    self,
    index: Union[str, List[str]],
    columns: str,
    values: str,
    aggfunc: str = "first",
    where: Optional[str] = None,
    on_in: Optional[List[Any]] = None,
    group_by: Optional[Union[str, List[str]]] = None,
    order_by: Optional[Union[str, List[str]]] = None,
    limit: Optional[int] = None,
    fill_value: Any = None,
) -> pd.DataFrame
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `index` | `Union[str, List[str]]` | Column(s) to use as row index |
| `columns` | `str` | Column whose values will become column headers |
| `values` | `str` | Column containing values to aggregate |
| `aggfunc` | `str` | Aggregation function (default 'first') |
| `where` | `Optional[str]` | WHERE clause to filter before pivoting |
| `on_in` | `Optional[List[Any]]` | Values to include in IN clause for columns |
| `group_by` | `Optional[Union[str, List[str]]]` | GROUP BY columns |
| `order_by` | `Optional[Union[str, List[str]]]` | ORDER BY columns |
| `limit` | `Optional[int]` | Row limit |
| `fill_value` | `Any` | Value to use for missing cells |

**Returns:** `pd.DataFrame` - Pivoted DataFrame

##### `ppivot()`

Wide pivot using pandas pivot_table.

```python
def ppivot(
    self,
    index: Union[str, List[str]],
    columns: Union[str, List[str]],
    values: Optional[Union[str, List[str]]] = None,
    aggfunc: str = "mean",
    where: Optional[str] = None,
    params: Optional[Sequence[Any]] = None,
    order_by: Optional[Union[str, List[str]]] = None,
    limit: Optional[int] = None,
    fill_value: Any = None,
    dropna: bool = True,
    **kwargs,
) -> pd.DataFrame
```

**Returns:** `pd.DataFrame` - Pivoted DataFrame using pandas pivot_table

##### `upsert()`

Upsert rows from DataFrame according to primary keys, overwriting existing rows.

```python
def upsert(self, df: pd.DataFrame, keys: list, partition_by: Optional[list] = None) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | `pd.DataFrame` | DataFrame with rows to upsert |
| `keys` | `list` | Primary key column names for deduplication |
| `partition_by` | `Optional[list]` | Partition columns for Hive-style partitioning |

**Raises:** `ValueError` if DataFrame contains duplicate rows based on keys

##### `compact()`

Compact partition directories with multiple parquet files into single parquet files.

```python
def compact(
    self,
    compression: str = "zstd",
    max_workers: int = 8,
    engine: str = "pyarrow",
) -> List[str]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `compression` | `str` | Compression codec ('zstd', 'snappy', 'gzip', etc.) |
| `max_workers` | `int` | Maximum number of parallel workers |
| `engine` | `str` | Parquet engine ('pyarrow' or 'fastparquet') |

**Returns:** `List[str]` - List of relative partition paths that were compacted

##### `refresh()`

Refresh DuckDB view after manual file changes.

```python
def refresh(self) -> None
```

##### `close()`

Close the DuckDB connection if owned by this instance.

```python
def close(self) -> None
```

##### `drop()`

Drop the underlying DuckDB view, if it exists.

```python
def drop(self) -> None
```

#### Context Manager

```python
with DuckTable("/path/to/data") as dt:
    df = dt.select(where="id > 100")
```

---

### DuckPQ

Database-like manager for a directory of Hive-partitioned Parquet tables.

```python
from parquool import DuckPQ
```

DuckPQ wraps a single DuckDB connection and a set of Parquet-backed tables (one directory per table) under a common root directory.

#### Constructor

```python
DuckPQ(
    root_path: Union[str, Path],
    database: Optional[Union[str, duckdb.DuckDBPyConnection]] = None,
    config: Optional[Dict[str, Any]] = None,
    threads: Optional[int] = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `root_path` | `Union[str, Path]` | Root directory for the Parquet database |
| `database` | `Optional[Union[str, duckdb.DuckDBPyConnection]]` | DuckDB connection or file path |
| `config` | `Optional[Dict[str, Any]]` | Extra DuckDB connection config |
| `threads` | `Optional[int]` | Number of DuckDB threads |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `root_path` | `Path` | Root directory path |
| `con` | `duckdb.DuckDBPyConnection` | Shared DuckDB connection |
| `tables` | `Dict[str, DuckTable]` | Table name to DuckTable mapping |

#### Methods

##### `register()`

Register table directories under root_path as DuckTable instances.

```python
def register(self, name: Optional[str] = None) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `Optional[str]` | Specific table name to register. If None, registers all subdirectories |

##### `registrable()`

List unregistered table directories under the root path.

```python
def registrable(self) -> List[str]
```

**Returns:** `List[str]` - List of directory names that could be registered

##### `attach()`

Register a pandas DataFrame as a DuckDB relation.

```python
def attach(
    self,
    name: str,
    df: pd.DataFrame,
    replace: bool = True,
    materialize: bool = False,
) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Name of the DuckDB view or table |
| `df` | `pd.DataFrame` | DataFrame to expose to DuckDB |
| `replace` | `bool` | Whether to drop existing view/table with same name |
| `materialize` | `bool` | If True, create a temporary DuckDB table instead of a view |

##### `select()`

Select from a Parquet-backed table via DuckTable.

```python
def select(
    self,
    table: str,
    columns: Union[str, List[str]] = "*",
    where: Optional[str] = None,
    params: Optional[Sequence[Any]] = None,
    group_by: Optional[Union[str, List[str]]] = None,
    having: Optional[str] = None,
    order_by: Optional[Union[str, List[str]]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    distinct: bool = False,
) -> pd.DataFrame
```

**Returns:** `pd.DataFrame` with query results

##### `upsert()`

Upsert rows from a DataFrame into a Parquet-backed table.

```python
def upsert(
    self,
    table: str,
    df: pd.DataFrame,
    keys: List[str],
    partition_by: Optional[List[str]] = None,
) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `table` | `str` | Table name |
| `df` | `pd.DataFrame` | Input DataFrame to upsert |
| `keys` | `List[str]` | Primary key column names |
| `partition_by` | `Optional[List[str]]` | Partition columns |

##### `compact()`

Compact partition directories of a Parquet-backed table.

```python
def compact(
    self,
    table: str,
    compression: str = "zstd",
    max_workers: int = 8,
    engine: str = "pyarrow",
) -> List[str]
```

**Returns:** `List[str]` - List of relative partition paths that were compacted

##### `execute()`

Execute arbitrary SQL on the shared DuckDB connection.

```python
def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> duckdb.DuckDBPyRelation
```

**Returns:** `duckdb.DuckDBPyRelation`

##### `query()`

Execute a raw SQL query and return results as a pandas DataFrame.

```python
def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame
```

##### `close()`

Close the underlying DuckDB connection if owned by DuckPQ.

```python
def close(self) -> None
```

#### Context Manager

```python
with DuckPQ(root_path="/data/tables") as db:
    df = db.select(table="sales", where="revenue > 1000")
```

---

## Usage Examples

### Basic DuckTable Operations

```python
from parquool import DuckTable
import pandas as pd

# Create a DuckTable
dt = DuckTable("/path/to/parquet_dir", name="my_data", create=True)

# Select with filtering
df = dt.select(
    columns=["id", "name", "value"],
    where="value > 100",
    order_by="id DESC",
    limit=50
)

# Check if empty
if not dt.empty:
    print(f"Schema: {dt.schema}")

# Refresh after external changes
dt.refresh()
dt.close()
```

### Using DuckPQ for Multiple Tables

```python
from parquool import DuckPQ

# Open database
db = DuckPQ(root_path="/data/warehouse")

# Auto-register all subdirectories as tables
db.register()

# List available tables
print(f"Registered tables: {list(db.tables.keys())}")
print(f"Registrable: {db.registrable()}")

# Query individual tables
sales = db.select(
    table="sales",
    columns=["date", "region", "revenue"],
    where="date >= '2024-01-01'"
)

# Cross-table SQL joins
result = db.query("""
    SELECT s.*, p.category, p.price
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.date >= '2024-01-01'
""")
```

### Upsert with Partitioning

```python
from parquool import DuckTable
import pandas as pd

dt = DuckTable("/data/sales", name="sales", create=True)

# New data to upsert
new_rows = pd.DataFrame([
    {"date": "2024-01-01", "region": "US", "revenue": 5000},
    {"date": "2024-01-02", "region": "EU", "revenue": 3000},
    {"date": "2024-01-01", "region": "US", "revenue": 6000},  # Updates existing
])

# Upsert by primary keys with Hive-style partitioning
dt.upsert(new_rows, keys=["date", "region"], partition_by=["region"])
```

### Pivot Operations

```python
from parquool import DuckTable

dt = DuckTable("/data/sales")

# DuckDB PIVOT (wide format)
pivot_df = dt.dpivot(
    index="region",
    columns="month",
    values="revenue",
    aggfunc="sum"
)

# Pandas pivot_table
pivot_df = dt.ppivot(
    index="region",
    columns="product_category",
    values="revenue",
    aggfunc="mean",
    fill_value=0
)
```

### Compacting Partitions

```python
from parquool import DuckTable

dt = DuckTable("/data/large_dataset")

# Compact all partitions with too many small files
compacted = dt.compact(
    compression="zstd",
    max_workers=4,
    engine="pyarrow"
)
print(f"Compacted partitions: {compacted}")
```
