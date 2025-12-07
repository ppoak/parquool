import re
import shutil
import uuid
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

import duckdb
import pandas as pd


class DuckTable:
    """Manage a directory of Parquet files through a DuckDB-backed view.

    This class exposes a convenient API for querying and mutating a parquet
    dataset stored in a directory. Internally it creates a DuckDB connection
    (in-memory by default or a file DB if db_path is provided) and registers a
    CREATE OR REPLACE VIEW over parquet_scan(...) (with Hive-style partitioning
    enabled).

    IMPORTANT:
        - If you pass an existing DuckDBPyConnection in `con`, the connection
          is treated as *externally owned* and `DuckTable.close()` will NOT
          close it. This is used by DuckPQ to share a single connection across
          many tables.
        - If you pass `con` as a path or leave it as None, DuckTable will
          create and own its own DuckDB connection and close it on `close()`.

    Typical usage:
        >>> dp = DuckTable("/path/to/parquet_dir")
        >>> df = dp.select("*", where="ds = '2025-01-01'")
        >>> dp.upsert_from_df(new_rows_df, keys=["id"], partition_by=["ds"])
        >>> dp.refresh()  # refresh the internal DuckDB view after external changes
        >>> dp.close()
    """

    def __init__(
        self,
        root_path: str,
        name: Optional[str] = None,
        create: bool = False,
        database: Optional[Union[str, duckdb.DuckDBPyConnection]] = None,
        threads: Optional[int] = None,
    ):
        """
        Args:
            root_path (str): Directory path that stores the parquet dataset.
            name (Optional[str]): The view name. Defaults to directory basename.
            create (bool): If True, create the directory if it doesn't exist.
            con (Optional[Union[str, duckdb.DuckDBPyConnection]]): Either:
                - DuckDB connection object (externally managed), or
                - Path to DuckDB database file, or
                - None (in-memory DB, internally managed).
            threads (Optional[int]): Number of threads used for operations.
        """
        self.root_path = Path(root_path)
        if not self.root_path.exists():
            if create:
                self.root_path.mkdir(exist_ok=True, parents=True)
            else:
                raise ValueError("Dataset path doesn't exist, check your spell.")
        if not self.root_path.is_dir():
            raise ValueError("Only directory is valid in root_path param")

        self.view_name = name or self._default_view_name(self.root_path)

        config: Dict[str, Any] = {}
        self.threads = threads or 1
        config["threads"] = self.threads

        # Distinguish whether the DuckDB connection is owned by this instance.
        if isinstance(database, duckdb.DuckDBPyConnection):
            # External connection: do NOT close it in close()
            self.con = database
            self._own_connection = False
        else:
            # Internal connection: this DuckTable owns it
            self.con = duckdb.connect(database=database or ":memory:", config=config)
            self._own_connection = True

        try:
            self.con.execute(f"SET threads={int(self.threads)}")
        except Exception:
            pass

        self.scan_pattern = self._infer_scan_pattern(self.root_path)
        if self._parquet_files_exist():
            self._create_or_replace_view()

    # ----------------- Private Helper Methods -----------------

    @staticmethod
    def _is_identifier(name: str) -> bool:
        """Check if a string is a valid DuckDB SQL identifier."""
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))

    @staticmethod
    def _quote_ident(name: str) -> str:
        """Quote a string if it's not a valid identifier for DuckDB."""
        if DuckTable._is_identifier(name):
            return name
        return '"' + name.replace('"', '""') + '"'

    @staticmethod
    def _default_view_name(path: Path) -> str:
        """Generate a default DuckDB view name from file/directory name."""
        name = Path(path).stem
        if not DuckTable._is_identifier(name):
            name = "ds_" + re.sub(r"[^A-Za-z0-9_]+", "_", name)
        return name or "dataset"

    @staticmethod
    def _infer_scan_pattern(path: Path) -> str:
        """Infer DuckDB's parquet_scan path glob based on the directory path."""
        path = Path(path)
        if path.is_dir():
            return str(path / "**/*.parquet")
        return str(path)

    @staticmethod
    def _local_tempdir(target_dir, prefix="__parquet_rewrite_"):
        """Generate a temporary directory for atomic operations under target_dir."""
        tmpdir = Path(target_dir) / f"{prefix}{uuid.uuid4().hex[:8]}"
        tmpdir.mkdir(exist_ok=True, parents=True)
        return tmpdir

    def _parquet_files_exist(self) -> bool:
        """Check if there are any parquet files under the dataset path."""
        for _ in self.root_path.rglob("*.parquet"):
            return True
        return False

    def _create_or_replace_view(self):
        """Create or replace the DuckDB view for current dataset."""
        view_ident = DuckTable._quote_ident(self.view_name)
        sql = (
            "CREATE OR REPLACE VIEW "
            f"{view_ident} AS "
            f"SELECT * FROM parquet_scan('{self.scan_pattern}', HIVE_PARTITIONING=1)"
        )
        self.con.execute(sql)

    def _copy_select_to_dir(
        self,
        select_sql: str,
        target_dir: str,
        partition_by: Optional[List[str]] = None,
        params: Optional[Sequence[Any]] = None,
        compression: str = "zstd",
    ):
        """Dump SELECT query result to parquet files under target_dir."""
        opts = ["FORMAT 'parquet'"]
        if compression:
            opts.append(f"COMPRESSION '{compression}'")
        if partition_by:
            cols = ", ".join(DuckTable._quote_ident(c) for c in partition_by)
            opts.append(f"PARTITION_BY ({cols})")
        options_sql = ", ".join(opts)
        sql = f"COPY ({select_sql}) TO '{target_dir}' ({options_sql})"
        self.con.execute(sql, params)

    def _copy_df_to_dir(
        self,
        df: pd.DataFrame,
        target: str,
        partition_by: Optional[List[str]] = None,
        compression: str = "zstd",
    ):
        """Write pandas DataFrame into partitioned parquet files."""
        reg_name = f"incoming_{uuid.uuid4().hex[:8]}"
        self.con.register(reg_name, df)
        opts = ["FORMAT 'parquet'"]
        if compression:
            opts.append(f"COMPRESSION '{compression}'")
        if partition_by:
            cols = ", ".join(DuckTable._quote_ident(c) for c in partition_by)
            opts.append(f"PARTITION_BY ({cols})")
        options_sql = ", ".join(opts)
        if partition_by:
            sql = (
                f"COPY (SELECT * FROM {DuckTable._quote_ident(reg_name)}) "
                f"TO '{target}' ({options_sql})"
            )
        else:
            sql = (
                f"COPY (SELECT * FROM {DuckTable._quote_ident(reg_name)}) "
                f"TO '{target}/data_0.parquet' ({options_sql})"
            )
        self.con.execute(sql)
        self.con.unregister(reg_name)

    def _atomic_replace_dir(self, new_dir: Union[Path, str], old_dir: Union[Path, str]):
        """Atomically replace a directory's contents."""
        new_dir = Path(new_dir)
        old_dir = Path(old_dir)
        if old_dir.exists():
            shutil.rmtree(str(old_dir))
        new_dir.replace(old_dir)

    # ----------------- Upsert Internal Logic -----------------

    def _upsert_no_exist(self, df: pd.DataFrame, partition_by: Optional[list]) -> None:
        """Upsert logic branch if no existing parquet files."""
        tmpdir = self._local_tempdir(self.root_path.parent)
        try:
            self._copy_df_to_dir(
                df,
                target=str(tmpdir),
                partition_by=partition_by,
            )
            self._atomic_replace_dir(tmpdir, self.root_path)
        finally:
            if tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)
        self.refresh()

    def _upsert_existing(
        self, df: pd.DataFrame, keys: list, partition_by: Optional[list]
    ) -> None:
        """Upsert logic branch if existing parquet files already present."""
        tmpdir = self._local_tempdir(self.root_path.parent)
        base_cols = self.columns
        all_cols = ", ".join(DuckTable._quote_ident(c) for c in base_cols)
        key_expr = ", ".join(DuckTable._quote_ident(k) for k in keys)
        temp_name = f"newdata_{uuid.uuid4().hex[:6]}"
        self.con.register(temp_name, df)
        parts_tbl: Optional[str] = None

        try:
            if not partition_by:
                out_path = tmpdir / "data_0.parquet"
                sql = f"""
                    COPY (
                        SELECT {all_cols} FROM (
                            SELECT *, ROW_NUMBER() OVER (PARTITION BY {key_expr} ORDER BY is_new DESC) AS rn
                            FROM (
                                SELECT {all_cols}, 0 as is_new FROM {DuckTable._quote_ident(self.view_name)}
                                UNION ALL
                                SELECT {all_cols}, 1 as is_new FROM {DuckTable._quote_ident(temp_name)}
                            )
                        ) WHERE rn=1
                    ) TO '{out_path}' (FORMAT 'parquet', COMPRESSION 'zstd')
                """
                self.con.execute(sql)
                dst = self.root_path / "data_0.parquet"
                if dst.exists():
                    dst.unlink()
                shutil.move(str(out_path), str(dst))
            else:
                parts_tbl = f"parts_{uuid.uuid4().hex[:6]}"
                affected = df[partition_by].drop_duplicates()
                self.con.register(parts_tbl, affected)
                part_cols_ident = ", ".join(
                    DuckTable._quote_ident(c) for c in partition_by
                )
                partition_by_clause = f"PARTITION_BY ({part_cols_ident})"
                old_sql = (
                    f"SELECT {all_cols}, 0 AS is_new "
                    f"FROM {DuckTable._quote_ident(self.view_name)} AS e "
                    f"JOIN {DuckTable._quote_ident(parts_tbl)} AS p USING ({part_cols_ident})"
                )
                sql = f"""
                    COPY (
                        SELECT {all_cols} FROM (
                            SELECT *, ROW_NUMBER() OVER (PARTITION BY {key_expr} ORDER BY is_new DESC) AS rn
                            FROM (
                                {old_sql}
                                UNION ALL
                                SELECT {all_cols}, 1 as is_new FROM {DuckTable._quote_ident(temp_name)}
                            )
                        ) WHERE rn=1
                    ) TO '{tmpdir}'
                      (FORMAT 'parquet', COMPRESSION 'zstd', {partition_by_clause})
                """
                self.con.execute(sql)

                # move each partition subdir from tmpdir -> root_path
                subdirs = [d.name for d in tmpdir.iterdir() if d.is_dir()]
                for subdir in subdirs:
                    src = tmpdir / subdir
                    dst = self.root_path / subdir
                    if dst.exists():
                        if dst.is_dir():
                            shutil.rmtree(str(dst))
                        else:
                            dst.unlink()
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
        finally:
            try:
                self.con.unregister(temp_name)
            except Exception:
                pass
            if parts_tbl is not None:
                try:
                    self.con.unregister(parts_tbl)
                except Exception:
                    pass
            if tmpdir.exists():
                shutil.rmtree(str(tmpdir), ignore_errors=True)
            self.refresh()

    # ----------------- Context/Resource Management -----------------

    def close(self):
        """Close the DuckDB connection if it is owned by this instance."""
        if getattr(self, "_own_connection", True):
            try:
                self.con.close()
            except Exception:
                pass

    def drop_view(self):
        """Drop the underlying DuckDB view, if it exists."""
        view_ident = DuckTable._quote_ident(self.view_name)
        try:
            self.con.execute(f"DROP VIEW IF EXISTS {view_ident}")
        except Exception:
            pass

    def __enter__(self):
        """Enable usage as a context manager."""
        return self

    def __exit__(self, exc_type, exc, tb):
        """Context manager exit: close connection if owned."""
        self.close()

    def __str__(self):
        return f"DuckTable@<{self.root_path}>(Columns={self.columns})"

    def __repr__(self):
        return self.__str__()

    # ----------------- Public Query/Mutation Methods -----------------

    @property
    def empty(self) -> bool:
        """Return True if the parquet path is empty."""
        return not self._parquet_files_exist()

    def refresh(self):
        """Refresh DuckDB view after manual file changes."""
        if self._parquet_files_exist():
            self._create_or_replace_view()
        else:
            # If no parquet files, it's fine to just drop the view.
            self.drop_view()

    def execute(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> duckdb.DuckDBPyRelation:
        """Execute a raw SQL query and return results as a DataFrame."""
        return self.con.execute(sql, params or [])

    sql = execute

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame:
        return self.execute(sql, params=params).df()

    @property
    def schema(self) -> pd.DataFrame:
        """Get the schema (column info) of current parquet dataset."""
        view_ident = DuckTable._quote_ident(self.view_name)
        return self.con.execute(f"DESCRIBE {view_ident}").df()

    @property
    def columns(self) -> List[str]:
        """List all columns in the dataset."""
        df = self.schema
        if "column_name" in df.columns:
            return df["column_name"].tolist()
        if "name" in df.columns:
            return df["name"].tolist()
        return df.iloc[:, 0].astype(str).tolist()

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
    ) -> pd.DataFrame:
        """Query current dataset with flexible SQL generated automatically."""
        view_ident = DuckTable._quote_ident(self.view_name)
        col_sql = columns if isinstance(columns, str) else ", ".join(columns)
        sql_parts: List[str] = ["SELECT"]
        if distinct:
            sql_parts.append("DISTINCT")
        sql_parts.append(col_sql)
        sql_parts.append(f"FROM {view_ident}")
        bind_params = list(params or [])
        if where:
            sql_parts.append("WHERE")
            sql_parts.append(where)
        if group_by:
            group_sql = group_by if isinstance(group_by, str) else ", ".join(group_by)
            sql_parts.append("GROUP BY " + group_sql)
        if having:
            sql_parts.append("HAVING " + having)
        if order_by:
            order_sql = order_by if isinstance(order_by, str) else ", ".join(order_by)
            sql_parts.append("ORDER BY " + order_sql)
        if limit is not None:
            sql_parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            sql_parts.append(f"OFFSET {int(offset)}")
        final = " ".join(sql_parts)
        return self.execute(final, bind_params).df()

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
    ) -> pd.DataFrame:
        """Pivot the parquet dataset using DuckDB PIVOT statement."""
        if isinstance(index, str):
            index_cols = [index]
        else:
            index_cols = list(index)
        select_cols = index_cols + [columns, values]
        sel_sql = (
            f"SELECT {', '.join(DuckTable._quote_ident(c) for c in select_cols)} "
            f"FROM {DuckTable._quote_ident(self.view_name)}"
        )
        if where:
            sel_sql += f" WHERE {where}"

        pivot_on = DuckTable._quote_ident(columns)
        if on_in:
            in_vals = []
            for v in on_in:
                if isinstance(v, str):
                    in_vals.append(f"'{v}'")
                else:
                    in_vals.append(str(v))
            pivot_on += f" IN ({', '.join(in_vals)})"

        pivot_using = f"{aggfunc}({DuckTable._quote_ident(values)})"

        sql_lines = [
            f"PIVOT ({sel_sql})",
            f"ON {pivot_on}",
            f"USING {pivot_using}",
        ]
        if group_by:
            if isinstance(group_by, str):
                groupby_expr = DuckTable._quote_ident(group_by)
            else:
                groupby_expr = ", ".join(DuckTable._quote_ident(c) for c in group_by)
            sql_lines.append(f"GROUP BY {groupby_expr}")
        if order_by:
            if isinstance(order_by, str):
                order_expr = DuckTable._quote_ident(order_by)
            else:
                order_expr = ", ".join(DuckTable._quote_ident(c) for c in order_by)
            sql_lines.append(f"ORDER BY {order_expr}")
        if limit:
            sql_lines.append(f"LIMIT {int(limit)}")

        sql = "\n".join(sql_lines)
        df = self.execute(sql).df()
        if fill_value is not None:
            df = df.fillna(fill_value)
        return df

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
    ) -> pd.DataFrame:
        """Wide pivot using Pandas pivot_table."""
        select_cols: List[str] = []
        for part in (index, columns, values or []):
            if part is None:
                continue
            if isinstance(part, str):
                select_cols.append(part)
            else:
                select_cols.extend(part)
        select_cols = list(dict.fromkeys(select_cols))
        df = self.select(
            columns=select_cols,
            where=where,
            params=params,
            order_by=order_by,
            limit=limit,
        )
        return pd.pivot_table(
            df,
            index=index,
            columns=columns,
            values=values,
            aggfunc=aggfunc,
            fill_value=fill_value,
            dropna=dropna,
            **kwargs,
        )

    def upsert(self, df: pd.DataFrame, keys: list, partition_by: Optional[list] = None):
        """Upsert rows from DataFrame according to primary keys, overwrite existing rows."""
        if df.duplicated(subset=keys).any():
            raise ValueError("DataFrame contains duplicate rows based on keys.")
        if not self._parquet_files_exist():
            self._upsert_no_exist(df, partition_by)
        else:
            self._upsert_existing(df, keys, partition_by)


class DuckPQ:
    """Database-like manager for a directory of Hive-partitioned Parquet tables.

    DuckPQ wraps a single DuckDB connection and a set of Parquet-backed tables
    (one directory per table) under a common root directory. Each table
    directory is handled by a DuckTable instance, and a DuckDB VIEW is
    created for each table name, so you can query them using SQL on the shared
    DuckDB connection.

    On initialization:
        - A DuckDB connection is created or reused.
        - All immediate subdirectories under `root_dir` are treated as tables.
        - For each table directory, a DuckTable is instantiated and stored
          in `self.tables[table_name]`.

    Typical usage:
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

    Attributes:
        root_path: Root directory containing parquet table directories.
        database: Shared DuckDB connection.
        tables: Mapping table_name -> DuckTable instance.
    """

    def __init__(
        self,
        root_path: Union[str, Path],
        database: Optional[Union[str, duckdb.DuckDBPyConnection]] = None,
        config: Optional[Dict[str, Any]] = None,
        threads: Optional[int] = None,
    ):
        """Initialize DuckPQ.

        Args:
            root_path: Root directory for the Parquet database. Each immediate
                subdirectory is treated as a table.
            database: DuckDB database spec:
                - DuckDBPyConnection instance: reuse this connection
                  (DuckPQ will not close it).
                - String path: DuckDB file path, will call duckdb.connect.
                - None: use in-memory DuckDB (":memory:").
            config: Extra DuckDB connection config, merged into duckdb.connect.
            threads: Number of DuckDB threads to set via "SET threads=...".
        """
        self.root_path = Path(root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)

        # Set up DuckDB connection
        if isinstance(database, duckdb.DuckDBPyConnection):
            self.con = database
            self._own_connection = False
        else:
            db_path = database or ":memory:"
            cfg: Dict[str, Any] = dict(config or {})
            if threads is not None:
                cfg["threads"] = int(threads)
            self.con = duckdb.connect(database=db_path, config=cfg)
            self._own_connection = True
            if threads is not None:
                try:
                    self.con.execute(f"SET threads={int(threads)}")
                except Exception:
                    # Ignore inability to set threads
                    pass

        # Table name -> DuckTable
        self.tables: Dict[str, DuckTable] = {}

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_or_create_table(self, table: str) -> DuckTable:
        """Get an existing DuckTable for table, or create and attach it.

        If the table is not yet known, a new directory root_dir/table is
        created (if missing) and a DuckTable is created and registered.

        Args:
            table: Table name.

        Returns:
            DuckTable instance for the table.
        """
        if table in self.tables:
            return self.tables[table]

        root_path = self.root_path / table
        dp = DuckTable(
            root_path=str(root_path),
            name=table,
            create=True,
            database=self.con,
        )
        self.tables[table] = dp
        return dp

    # ------------------------------------------------------------------ #
    # Public API: register DuckTable for further operations
    # ------------------------------------------------------------------ #

    def registrable(self):
        """Registrable table under root path"""
        tables = []
        for path in self.root_path.iterdir():
            if path.is_dir() and path.name not in self.tables:
                tables.append(path.name)
        return tables

    def register(self, name: Optional[str] = None) -> None:
        """Register table directories under root_dir and attach them."""
        if name is not None:
            dp = self._get_or_create_table(name)
            self.tables[name] = dp
            return

        for p in self.root_path.iterdir():
            if not p.is_dir():
                continue
            table_name = p.name
            if table_name in self.tables:
                continue
            dp = DuckTable(
                root_path=str(p),
                name=table_name,
                create=False,
                database=self.con,
            )
            self.tables[table_name] = dp

    # ------------------------------------------------------------------ #
    # Public API: delegate to DuckTable for single-table operations
    # ------------------------------------------------------------------ #

    def upsert(
        self,
        table: str,
        df: pd.DataFrame,
        keys: List[str],
        partition_by: Optional[List[str]] = None,
    ) -> None:
        """Upsert rows from a DataFrame into a Parquet-backed table.

        This will create the table directory under root_dir if it does not
        exist yet. Internally it delegates to DuckTable.upsert_from_df.

        Args:
            table: Logical table name (directory name and view name).
            df: Input pandas DataFrame to upsert.
            keys: Primary key column names used to deduplicate and upsert.
            partition_by: Optional list of partition columns used to create
                Hive-style partitions under the table directory.
        """
        dp = self._get_or_create_table(table)
        dp.upsert(df=df, keys=keys, partition_by=partition_by)

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
    ) -> pd.DataFrame:
        """Select from a Parquet-backed table via DuckTable.

        Args:
            table: Table name to query.
            columns: Column list or "*" for all columns.
            where: Optional WHERE clause string.
            params: Optional sequence of bind parameters for WHERE.
            group_by: Optional GROUP BY columns or expression.
            having: Optional HAVING clause.
            order_by: Optional ORDER BY columns or expression.
            limit: Optional row limit.
            offset: Optional row offset.
            distinct: Whether to select DISTINCT.

        Returns:
            pandas.DataFrame with query results.
        """
        dp = self._get_or_create_table(table)
        return dp.select(
            columns=columns,
            where=where,
            params=params,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
            distinct=distinct,
        )

    # ------------------------------------------------------------------ #
    # Public API: connection-level SQL
    # ------------------------------------------------------------------ #

    def execute(
        self,
        sql: str,
        params: Optional[Sequence[Any]] = None,
    ) -> duckdb.DuckDBPyRelation:
        """Execute arbitrary SQL on the shared DuckDB connection.

        This method operates at the connection level, so it can query multiple
        tables, perform joins, aggregations, create regular DuckDB tables or
        views, etc. Parquet-backed tables appear as normal views (by table
        name) inside this connection.

        Args:
            sql: SQL statement to execute.
            params: Optional sequence of bind parameters.

        Returns:
            the DuckDB relation.
        """
        return self.con.execute(sql, params or [])

    # Alias for execute
    sql = execute

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame:
        return self.execute(sql, params=params).df()

    # ------------------------------------------------------------------ #
    # Resource management
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Close the underlying DuckDB connection if owned by DuckPQ.

        After calling close(), the DuckPQ instance should not be used for
        further operations.
        """
        if getattr(self, "_own_connection", False):
            try:
                self.con.close()
            except Exception:
                pass
        self.tables.clear()

    def __enter__(self) -> "DuckPQ":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close connection if needed."""
        self.close()

    def __str__(self):
        tables = "\n".join([f"{name} -> {pq}" for name, pq in self.tables.items()])
        return f"DuckTable@<{self.root_path}>(tables=\n{tables}\n)\n"

    def __repr__(self):
        return self.__str__()
