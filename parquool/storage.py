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


class DuckParquet:
    """Manage a directory of Parquet files through a DuckDB-backed view.

    This class exposes a convenient API for querying and mutating a parquet
    dataset stored in a directory. Internally it creates a DuckDB connection
    (in-memory by default or a file DB if db_path is provided) and registers a
    CREATE OR REPLACE VIEW over parquet_scan(...) (with Hive-style partitioning
    enabled). Query helpers (select, raw_query, dpivot, ppivot, count, etc.)
    operate against that view. Mutation helpers (upsert_from_df, update,
    delete) rewrite Parquet files atomically into a temporary directory and then
    replace the dataset directory to ensure safe, consistent updates. Partitioning
    behavior is supported for writes via the partition_by parameter.

    Typical usage:
        >>> dp = DuckParquet("/path/to/parquet_dir")
        >>> df = dp.select("*", where="ds = '2025-01-01'")
        >>> dp.upsert_from_df(new_rows_df, keys=["id"], partition_by=["ds"])
        >>> dp.refresh()  # refresh the internal DuckDB view after external changes
        >>> dp.close()

    Important behavior:
        - A DuckDB view named view_name is created automatically to read the
          parquet files using parquet_scan('{scan_pattern}', HIVE_PARTITIONING=1).
        - Mutations are implemented by creating parquet files in a local
          temporary directory and then atomically replacing the dataset
          directory contents. This ensures updates are all-or-nothing.
        - Partitioned writes will create subdirectories for each partition value.
        - The class attempts to set DuckDB threads according to the threads
          parameter but will silently continue if the setting cannot be applied.
        - Identifiers are quoted as needed to be safe SQL identifiers.

    Attributes:
        dataset_path (str): Absolute path of the Parquet dataset directory.
        view_name (str): The name of the DuckDB view exposing the dataset.
        con (duckdb.DuckDBPyConnection): Active DuckDB connection object.
        threads (int): Number of threads configured for DuckDB operations.
        scan_pattern (str): Glob pattern passed to parquet_scan to read files.

    Raises:
        ValueError: If dataset_path exists but is not a directory.

    Notes:
        - The class supports use as a context manager: use "with DuckParquet(...)"
          to ensure the DuckDB connection is closed on exit.
        - For large datasets or heavy write workloads, tune the threads and
          partition_by arguments to optimize performance.
    """

    def __init__(
        self,
        dataset_path: str,
        name: Optional[str] = None,
        create: bool = False,
        db_path: str = None,
        threads: Optional[int] = None,
    ):
        """Initializes the DuckParquet object.

        Args:
            dataset_path (str): Directory path that stores the parquet dataset.
            name (Optional[str]): The view name. Defaults to directory basename.
            create (bool): If True, create the directory if it doesn't exist.
            db_path (str): Path to DuckDB database file. Defaults to in-memory.
            threads (Optional[int]): Number of threads used for partition operations.

        Raises:
            ValueError: If the dataset_path is not a directory.
        """
        self.dataset_path = Path(dataset_path)
        if not self.dataset_path.exists():
            if create:
                self.dataset_path.mkdir(exist_ok=True, parents=True)
            else:
                raise ValueError("Dataset path doesn't exist, check your spell.")
        if not self.dataset_path.is_dir():
            raise ValueError("Only directory is valid in dataset_path param")
        self.view_name = name or self._default_view_name(self.dataset_path)
        config = {}
        self.threads = threads or 1
        config["threads"] = self.threads
        self.con = duckdb.connect(database=db_path or ":memory:", config=config)
        try:
            self.con.execute(f"SET threads={int(self.threads)}")
        except Exception:
            pass
        self.scan_pattern = self._infer_scan_pattern(self.dataset_path)
        if self._parquet_files_exist():
            self._create_or_replace_view()

    # ----------------- Private Helper Methods -----------------

    @staticmethod
    def _is_identifier(name: str) -> bool:
        """Check if a string is a valid DuckDB SQL identifier.

        Args:
            name (str): The identifier to check.

        Returns:
            bool: True if valid identifier, else False.
        """
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))

    @staticmethod
    def _quote_ident(name: str) -> str:
        """Quote a string if it's not a valid identifier for DuckDB.

        Args:
            name (str): The identifier to quote.

        Returns:
            str: Quoted identifier as DuckDB requires.
        """
        if DuckParquet._is_identifier(name):
            return name
        return '"' + name.replace('"', '""') + '"'

    @staticmethod
    def _default_view_name(path: Path) -> str:
        """Generate a default DuckDB view name from file/directory name.

        Args:
            path (str): Directory or parquet file path.

        Returns:
            str: Default view name.
        """
        name = Path(path).stem
        if not DuckParquet._is_identifier(name):
            name = "ds_" + re.sub(r"[^A-Za-z0-9_]+", "_", name)
        return name or "dataset"

    @staticmethod
    def _infer_scan_pattern(path: Path) -> str:
        """Infer DuckDB's parquet_scan path glob based on the directory path.

        Args:
            path (str): Target directory.

        Returns:
            str: Glob scan pattern.
        """
        path = Path(path)
        if path.is_dir():
            return str(path / "**/*.parquet")
        return path

    @staticmethod
    def _local_tempdir(target_dir, prefix="__parquet_rewrite_"):
        """Generate a temporary directory for atomic operations under target_dir.

        Args:
            target_dir (str): Directory for temp.

        Returns:
            str: Path to temp directory.
        """
        tmpdir = Path(target_dir) / f"{prefix}{uuid.uuid4().hex[:8]}"
        tmpdir.mkdir(exist_ok=True, parents=True)
        return tmpdir

    def _parquet_files_exist(self) -> bool:
        """Check if there are any parquet files under the dataset path.

        Returns:
            bool: True if any parquet exists, else False.
        """
        for _ in self.dataset_path.rglob("*.parquet"):
            return True
        return False

    def _create_or_replace_view(self):
        """Create or replace the DuckDB view for current dataset."""
        view_ident = DuckParquet._quote_ident(self.view_name)
        sql = f"CREATE OR REPLACE VIEW {view_ident} AS SELECT * FROM parquet_scan('{self.scan_pattern}', HIVE_PARTITIONING=1)"
        self.con.execute(sql)

    def _copy_select_to_dir(
        self,
        select_sql: str,
        target_dir: str,
        partition_by: Optional[List[str]] = None,
        params: Optional[Sequence[Any]] = None,
        compression: str = "zstd",
    ):
        """Dump SELECT query result to parquet files under target_dir.

        Args:
            select_sql (str): SELECT SQL to copy data from.
            target_dir (str): Target directory to store parquet files.
            partition_by (Optional[List[str]]): Partition columns.
            params (Optional[Sequence[Any]]): SQL bind parameters.
            compression (str): Parquet compression, default 'zstd'.
        """
        opts = [f"FORMAT 'parquet'"]
        if compression:
            opts.append(f"COMPRESSION '{compression}'")
        if partition_by:
            cols = ", ".join(DuckParquet._quote_ident(c) for c in partition_by)
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
        """Write pandas DataFrame into partitioned parquet files.

        Args:
            df (pd.DataFrame): Source dataframe.
            target (str): Target directory.
            partition_by (Optional[List[str]]): Partition columns.
            compression (str): Parquet compression.
        """
        reg_name = f"incoming_{uuid.uuid4().hex[:8]}"
        self.con.register(reg_name, df)
        opts = [f"FORMAT 'parquet'"]
        if compression:
            opts.append(f"COMPRESSION '{compression}'")
        if partition_by:
            cols = ", ".join(DuckParquet._quote_ident(c) for c in partition_by)
            opts.append(f"PARTITION_BY ({cols})")
        options_sql = ", ".join(opts)
        if partition_by:
            sql = f"COPY (SELECT * FROM {DuckParquet._quote_ident(reg_name)}) TO '{target}' ({options_sql})"
        else:
            sql = f"COPY (SELECT * FROM {DuckParquet._quote_ident(reg_name)}) TO '{target}/data_0.parquet' ({options_sql})"
        self.con.execute(sql)
        self.con.unregister(reg_name)

    def _atomic_replace_dir(self, new_dir: Union[Path, str], old_dir: Union[Path, str]):
        """Atomically replace a directory's contents.

        Args:
            new_dir (Path or str): Temporary directory with new data.
            old_dir (Path or str): Target directory to replace.
        """
        new_dir = Path(new_dir)
        old_dir = Path(old_dir)
        if old_dir.exists():
            shutil.rmtree(str(old_dir))
        new_dir.replace(old_dir)

    # ----------------- Upsert Internal Logic -----------------

    def _upsert_no_exist(self, df: pd.DataFrame, partition_by: Optional[list]) -> None:
        """Upsert logic branch if no existing parquet files.

        Args:
            df (pd.DataFrame): Raw DataFrame
            partition_by (Optional[list]): Partition columns
        """
        tmpdir = self._local_tempdir(self.dataset_path.parent)
        try:
            self._copy_df_to_dir(
                df,
                target=tmpdir,
                partition_by=partition_by,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)
        self.refresh()

    def _upsert_existing(
        self, df: pd.DataFrame, keys: list, partition_by: Optional[list]
    ) -> None:
        """Upsert logic branch if existing parquet files already present.

        Args:
            df (pd.DataFrame): Raw DataFrame
            keys (list): Primary key columns
            partition_by (Optional[list]): Partition columns
        """
        tmpdir = self._local_tempdir(self.dataset_path.parent)
        base_cols = self.list_columns()
        all_cols = ", ".join(DuckParquet._quote_ident(c) for c in base_cols)
        key_expr = ", ".join(DuckParquet._quote_ident(k) for k in keys)

        temp_name = f"newdata_{uuid.uuid4().hex[:6]}"
        self.con.register(temp_name, df)

        try:
            if not partition_by:
                out_path = tmpdir / "data_0.parquet"
                sql = f"""
                    COPY (
                        SELECT {all_cols} FROM (
                            SELECT *, ROW_NUMBER() OVER (PARTITION BY {key_expr} ORDER BY is_new DESC) AS rn
                            FROM (
                                SELECT {all_cols}, 0 as is_new FROM {DuckParquet._quote_ident(self.view_name)}
                                UNION ALL
                                SELECT {all_cols}, 1 as is_new FROM {DuckParquet._quote_ident(temp_name)}
                            )
                        ) WHERE rn=1
                    ) TO '{out_path}' (FORMAT 'parquet', COMPRESSION 'zstd')
                """
                self.con.execute(sql)
                dst = self.dataset_path / "data_0.parquet"
                if dst.exists():
                    dst.unlink()
                shutil.move(str(out_path), str(dst))
            else:
                parts_tbl = f"parts_{uuid.uuid4().hex[:6]}"
                affected = df[partition_by].drop_duplicates()
                self.con.register(parts_tbl, affected)

                part_cols_ident = ", ".join(
                    DuckParquet._quote_ident(c) for c in partition_by
                )
                partition_by_clause = f"PARTITION_BY ({part_cols_ident})"

                old_sql = (
                    f"SELECT {all_cols}, 0 AS is_new "
                    f"FROM {DuckParquet._quote_ident(self.view_name)} AS e "
                    f"JOIN {DuckParquet._quote_ident(parts_tbl)} AS p USING ({part_cols_ident})"
                )

                sql = f"""
                    COPY (
                        SELECT {all_cols} FROM (
                            SELECT *, ROW_NUMBER() OVER (PARTITION BY {key_expr} ORDER BY is_new DESC) AS rn
                            FROM (
                                {old_sql}
                                UNION ALL
                                SELECT {all_cols}, 1 as is_new FROM {DuckParquet._quote_ident(temp_name)}
                            )
                        ) WHERE rn=1
                    ) TO '{tmpdir}'
                      (FORMAT 'parquet', COMPRESSION 'zstd', {partition_by_clause})
                """
                self.con.execute(sql)

                # move each partition subdir from tmpdir -> dataset_path using pathlib
                subdirs = [d.name for d in tmpdir.iterdir() if d.is_dir()]
                for subdir in subdirs:
                    src = tmpdir / subdir
                    dst = self.dataset_path / subdir
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
            try:
                self.con.unregister(parts_tbl)  # type: ignore
            except Exception:
                pass
            if tmpdir.exists():
                shutil.rmtree(str(tmpdir), ignore_errors=True)
            self.refresh()

    # ----------------- Context/Resource Management -----------------

    def close(self):
        """Close the DuckDB connection."""
        try:
            self.con.close()
        except Exception:
            pass

    def __enter__(self):
        """Enable usage as a context manager.

        Returns:
            DuckParquet: Current instance.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Context manager exit: close connection."""
        self.close()

    def __str__(self):
        return f"DuckParquet@<{self.dataset_path}>(Columns={self.list_columns()})\n"

    def __repr__(self):
        return self.__str__()

    # ----------------- Public Query/Mutation Methods -----------------

    @property
    def empty(self) -> bool:
        """Return true if the duck parquet path is empty"""
        return not self._parquet_files_exist()

    @property
    def columns(self) -> List[str]:
        """Get all base columns from current parquet duckdb view."""
        return self.list_columns()

    def refresh(self):
        """Refreshes DuckDB view after manual file changes."""
        self._create_or_replace_view()

    def raw_query(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> pd.DataFrame:
        """Execute a raw SQL query and return results as a DataFrame.

        Args:
            sql (str): SQL statement.
            params (Optional[Sequence[Any]]): Bind parameters.

        Returns:
            pd.DataFrame: Query results.
        """
        res = self.con.execute(sql, params or [])
        try:
            return res.df()
        except Exception:
            return res

    def get_schema(self) -> pd.DataFrame:
        """Get the schema (column info) of current parquet dataset.

        Returns:
            pd.DataFrame: DuckDB DESCRIBE result.
        """
        view_ident = DuckParquet._quote_ident(self.view_name)
        return self.con.execute(f"DESCRIBE {view_ident}").df()

    def list_columns(self) -> List[str]:
        """List all columns in the dataset.

        Returns:
            List[str]: Column names in the dataset.
        """
        df = self.get_schema()
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
        """Query current dataset with flexible SQL generated automatically.

        Args:
            columns (Union[str, List[str]]): Columns to select (* or list of str).
            where (Optional[str]): WHERE clause.
            params (Optional[Sequence[Any]]): Bind parameters for WHERE.
            group_by (Optional[Union[str, List[str]]]): GROUP BY columns.
            having (Optional[str]): HAVING clause.
            order_by (Optional[Union[str, List[str]]]): ORDER BY columns.
            limit (Optional[int]): Max rows to get.
            offset (Optional[int]): Row offset.
            distinct (bool): Whether to add DISTINCT clause.

        Returns:
            pd.DataFrame: Query results.
        """
        view_ident = DuckParquet._quote_ident(self.view_name)
        col_sql = columns if isinstance(columns, str) else ", ".join(columns)
        sql = ["SELECT"]
        if distinct:
            sql.append("DISTINCT")
        sql.append(col_sql)
        sql.append(f"FROM {view_ident}")
        bind_params = list(params or [])
        if where:
            sql.append("WHERE")
            sql.append(where)
        if group_by:
            group_sql = group_by if isinstance(group_by, str) else ", ".join(group_by)
            sql.append("GROUP BY " + group_sql)
        if having:
            sql.append("HAVING " + having)
        if order_by:
            order_sql = order_by if isinstance(order_by, str) else ", ".join(order_by)
            sql.append("ORDER BY " + order_sql)
        if limit is not None:
            sql.append(f"LIMIT {int(limit)}")
        if offset is not None:
            sql.append(f"OFFSET {int(offset)}")
        final = " ".join(sql)
        return self.raw_query(final, bind_params)

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
        """
        Pivot the parquet dataset using DuckDB PIVOT statement.
        Args:
            index: Output rows, will appear in SELECT and GROUP BY.
            columns: The column to turn into wide fields (PIVOT ON).
            values: Value column, aggregate target (PIVOT USING aggfunc(values)).
            aggfunc: Aggregate function, default 'first'.
            where: Filter applied in SELECT node.
            on_in: List of column values, restrict wide columns.
            group_by: Group by after pivot, usually same as index.
            order_by: Order by after pivot.
            limit: Row limit.
            fill_value: Fill missing values.
        Returns:
            pd.DataFrame: Wide pivoted DataFrame.
        """
        # Construct SELECT query for PIVOT source
        if isinstance(index, str):
            index_cols = [index]
        else:
            index_cols = list(index)
        select_cols = index_cols + [columns, values]
        sel_sql = f"SELECT {', '.join(DuckParquet._quote_ident(c) for c in select_cols)} FROM {DuckParquet._quote_ident(self.view_name)}"
        if where:
            sel_sql += f" WHERE {where}"

        # PIVOT ON
        pivot_on = DuckParquet._quote_ident(columns)
        # PIVOT ON ... IN (...)
        if on_in:
            in_vals = []
            for v in on_in:
                if isinstance(v, str):
                    in_vals.append(f"'{v}'")
                else:
                    in_vals.append(str(v))
            pivot_on += f" IN ({', '.join(in_vals)})"

        # PIVOT USING
        pivot_using = f"{aggfunc}({DuckParquet._quote_ident(values)})"

        # PIVOT
        sql_lines = [f"PIVOT ({sel_sql})", f"ON {pivot_on}", f"USING {pivot_using}"]

        # GROUP BY
        if group_by:
            if isinstance(group_by, str):
                groupby_expr = DuckParquet._quote_ident(group_by)
            else:
                groupby_expr = ", ".join(DuckParquet._quote_ident(c) for c in group_by)
            sql_lines.append(f"GROUP BY {groupby_expr}")

        # ORDER BY
        if order_by:
            if isinstance(order_by, str):
                order_expr = DuckParquet._quote_ident(order_by)
            else:
                order_expr = ", ".join(DuckParquet._quote_ident(c) for c in order_by)
            sql_lines.append(f"ORDER BY {order_expr}")

        # LIMIT
        if limit:
            sql_lines.append(f"LIMIT {int(limit)}")

        sql = "\n".join(sql_lines)
        df = self.raw_query(sql)
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
        """
        Wide pivot using Pandas pivot_table.

        Args:
            index: Indexes of pivot table.
            columns: Columns to expand.
            values: The value fields to aggregate.
            aggfunc: Pandas/numpy function name or callable.
            where: Optional filter.
            params: SQL bind params.
            order_by: Order output.
            limit: Row limit.
            fill_value: Defaults for missing.
            dropna: Drop missing columns.
            **kwargs: Any pandas.pivot_table compatible args.

        Returns:
            pd.DataFrame: Wide table.
        """
        select_cols = []
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

    def count(
        self, where: Optional[str] = None, params: Optional[Sequence[Any]] = None
    ) -> int:
        """Count rows in the dataset matching the given WHERE clause.

        Args:
            where (Optional[str]): WHERE condition to filter rows.
            params (Optional[Sequence[Any]]): Bind parameters.

        Returns:
            int: The count of rows.
        """
        view_ident = DuckParquet._quote_ident(self.view_name)
        sql = f"SELECT COUNT(*) AS c FROM {view_ident}"
        bind_params = list(params or [])
        if where:
            sql += " WHERE " + where
        return int(self.con.execute(sql, bind_params).fetchone()[0])

    def upsert_from_df(
        self, df: pd.DataFrame, keys: list, partition_by: Optional[list] = None
    ):
        """Upsert rows from DataFrame according to primary keys, overwrite existing rows.

        Args:
            df (pd.DataFrame): New data.
            keys (list): Primary key columns.
            partition_by (Optional[list]): Partition columns.
        """
        if df.duplicated(subset=keys).any():
            raise ValueError("DataFrame contains duplicate rows based on keys.")

        if not self._parquet_files_exist():
            self._upsert_no_exist(df, partition_by)
        else:
            self._upsert_existing(df, keys, partition_by)

    def update(
        self,
        set_map: Dict[str, Union[str, Any]],
        where: Optional[str] = None,
        partition_by: Optional[str] = None,
        params: Optional[Sequence[Any]] = None,
    ):
        """Update specified columns for rows matching WHERE.

        Args:
            set_map (Dict[str, Union[str, Any]]): {column: value or SQL expr}.
            where (Optional[str]): WHERE clause.
            partition_by (Optional[str]): Partition column.
            params (Optional[Sequence[Any]]): Bind parameters for WHERE.
        """
        if self.dataset_path.is_file():
            pass
        view_ident = DuckParquet._quote_ident(self.view_name)
        base_cols = self.list_columns()
        bind_params = list(params or [])
        select_exprs = []
        for col in base_cols:
            col_ident = DuckParquet._quote_ident(col)
            if col in set_map:
                val = set_map[col]
                if where:
                    if isinstance(val, str):
                        expr = f"CASE WHEN ({where}) THEN ({val}) ELSE {col_ident} END AS {col_ident}"
                    else:
                        expr = f"CASE WHEN ({where}) THEN (?) ELSE {col_ident} END AS {col_ident}"
                        bind_params.append(val)
                else:
                    if isinstance(val, str):
                        expr = f"({val}) AS {col_ident}"
                    else:
                        expr = f"(?) AS {col_ident}"
                        bind_params.append(val)
            else:
                expr = f"{col_ident}"
            select_exprs.append(expr)
        select_sql = f"SELECT {', '.join(select_exprs)} FROM {view_ident}"
        tmpdir = self._local_tempdir(self.dataset_path.parent)
        try:
            self._copy_select_to_dir(
                select_sql,
                target_dir=tmpdir,
                partition_by=partition_by,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if tmpdir.exists():
                shutil.rmtree(str(tmpdir), ignore_errors=True)
        self.refresh()

    def delete(
        self,
        where: str,
        partition_by: Optional[str] = None,
        params: Optional[Sequence[Any]] = None,
    ):
        """Delete rows matching the WHERE clause.

        Args:
            where (str): SQL WHERE condition for deletion.
            partition_by (Optional[str]): Partition column.
            params (Optional[Sequence[Any]]): Bind parameters for WHERE.
        """
        view_ident = DuckParquet._quote_ident(self.view_name)
        bind_params = list(params or [])
        select_sql = f"SELECT * FROM {view_ident} WHERE NOT ({where})"
        tmpdir = self._local_tempdir(self.dataset_path.parent)
        try:
            self._copy_select_to_dir(
                select_sql,
                target_dir=tmpdir,
                partition_by=partition_by,
                params=bind_params,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if tmpdir.exists():
                shutil.rmtree(str(tmpdir), ignore_errors=True)
        self.refresh()
