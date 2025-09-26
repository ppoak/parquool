import asyncio
import json
import os
import re
import random
import shutil
import time
import traceback
import uuid
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
    Callable,
    Tuple,
    Literal,
    AsyncIterator,
    TYPE_CHECKING,
)

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import dotenv
import agents
import litellm
import requests
import markdown
import duckdb
import pandas as pd
from retry import retry
from openai.types.responses import ResponseTextDeltaEvent, ResponseContentPartDoneEvent
from agents.extensions.models.litellm_model import LitellmModel


if TYPE_CHECKING:
    import chromadb


def setup_logger(
    name,
    level: str = logging.INFO,
    replace: bool = False,
    stream: bool = True,
    file: Union[Path, str] = None,
    clear: bool = False,
    style: Union[int, str] = 1,
    rotation: str = None,
    max_bytes: int = None,
    backup_count: int = None,
    when: str = None,
    interval: int = None,
) -> logging.Logger:
    """Create and configure a logger with optional stream/file handlers and rotation.

    This helper creates (or returns) a logging.Logger configured with optional
    console (stream) and file handlers. File handlers may use size-based or
    time-based rotation. If a logger with the same name already has handlers,
    the existing logger is returned unchanged (to avoid duplicate handlers).

    Args:
        name (str): Name of the logger.
        level (int or str, optional): Logging level (e.g. logging.INFO or 'INFO').
            Default: logging.INFO.
        replace (bool, optional): If True, instantiate a new Logger object even
            if one exists. If False, use logging.getLogger(name). Default: False.
        stream (bool, optional): If True, add a StreamHandler to emit logs to
            stderr/stdout. Default: True.
        file (Path or str, optional): Path to a file to also write logs to. If
            provided, a file handler is attached (regular or rotating depending
            on `rotation`). Default: None.
        clear (bool, optional): If True and `file` is provided, truncate the
            file before use. Default: False.
        style (int or logging.Formatter or str, optional): Select a built-in
            formatter style by integer (1..4). If not an int matching a built-in
            style, the value is used directly (e.g. a logging.Formatter instance
            or a custom format string). Default: 1.
        rotation (str, optional): Rotation mode for the file handler. Supported
            values: "size" (RotatingFileHandler), "time" (TimedRotatingFileHandler),
            or None (no rotation). Default: None.
        max_bytes (int, optional): Max bytes for size-based rotation. If not
            provided, defaults to 10 * 1024 * 1024 (10 MB).
        backup_count (int, optional): Number of backup files to keep for rotation.
            Defaults: 5 for size-based rotation, 7 for time-based rotation when not set.
        when (str, optional): When parameter for time-based rotation
            (e.g. 'midnight'). Default: "midnight" when rotation == "time".
        interval (int, optional): Interval for time-based rotation (in units
            defined by `when`). Default: 1.

    Returns:
        logging.Logger: The configured logger instance.
    """
    if file and clear:
        Path(file).write_text("")

    if not replace:
        logger = logging.getLogger(name)
    else:
        logger = logging.Logger(name, level=level)

    if logger.hasHandlers():
        return logger  # Avoid adding handlers multiple times

    logger.setLevel(level)

    # Define formatter styles (available to both stream and file handlers)
    formatter_styles = {
        1: logging.Formatter("[%(levelname)s]@[%(asctime)s]-[%(name)s]: %(message)s"),
        2: logging.Formatter(
            "[%(levelname)s]@[%(asctime)s]-[%(name)s]@[%(module)s:%(lineno)d]: %(message)s"
        ),
        3: logging.Formatter(
            "[%(levelname)s]@[%(asctime)s]-[%(name)s]@[%(module)s:%(lineno)d#%(funcName)s]: %(message)s"
        ),
        4: logging.Formatter(
            "[%(levelname)s]@[%(asctime)s]-[%(name)s]@[%(module)s:%(lineno)d#%(funcName)s~%(process)d:%(threadName)s]: %(message)s"
        ),
    }

    # Resolve formatter from style parameter
    formatter = None
    if isinstance(style, int):
        formatter = formatter_styles.get(style, formatter_styles[1])
    else:
        # style may be a logging.Formatter instance or a format string
        formatter = style

    if isinstance(formatter, str):
        formatter = logging.Formatter(formatter)

    if not isinstance(formatter, logging.Formatter):
        # Fallback to default if user provided an unexpected type
        formatter = formatter_styles[1]

    # Add stream handler if requested
    if stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # Add file handler if specified
    if file:
        if rotation == "size":
            file_handler = RotatingFileHandler(
                file,
                encoding="utf-8",
                maxBytes=max_bytes or 10 * 1024 * 1024,
                backupCount=backup_count or 5,
            )
        elif rotation == "time":
            file_handler = TimedRotatingFileHandler(
                file,
                encoding="utf-8",
                when=when or "midnight",
                interval=interval or 1,
                backupCount=backup_count or 7,
            )
        else:
            file_handler = logging.FileHandler(file, encoding="utf-8")

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def notify_task(
    sender: str = None,
    password: str = None,
    receiver: str = None,
    smtp_server: str = None,
    smtp_port: int = None,
    cc: str = None,
):
    """Decorator that runs a task and sends an email notification with its result.

    This decorator executes the wrapped function and sends an email containing the
    function result, execution parameters, start/end times and duration. Common return
    types receive special formatting:
      - pandas.DataFrame / pandas.Series: converted to markdown (head/tail if large).
      - dict: converted to a DataFrame then to markdown.
      - str or other objects: converted to str().
    If the wrapped function raises an exception, the decorator captures the traceback,
    sends a failure email containing the formatted traceback, and returns the exception's
    string representation (it does not re-raise the original exception).

    The decorator also parses markdown image/file links in the message:
      - Image files (.png, .jpg, .jpeg, .gif) are embedded inline using Content-ID (CID).
      - Text files are attached as text/plain attachments.
      - Non-text files are attached as binary (octet-stream) with base64 encoding.

    SMTP credentials and recipients can be provided as parameters or via environment
    variables when parameters are None:
      NOTIFY_TASK_SENDER, NOTIFY_TASK_PASSWORD, NOTIFY_TASK_RECEIVER,
      NOTIFY_TASK_SMTP_SERVER, NOTIFY_TASK_SMTP_PORT, NOTIFY_TASK_CC

    Note: The current implementation contains a probable bug where smtp_port is assigned
    from smtp_server instead of the intended environment variable. Verify smtp_port
    before use.

    Args:
        sender (str, optional): Sender email address. If None, read from
            NOTIFY_TASK_SENDER.
        password (str, optional): Sender email password or app-specific password. If None,
            read from NOTIFY_TASK_PASSWORD.
        receiver (str, optional): Comma-separated recipient addresses. If None, read
            from NOTIFY_TASK_RECEIVER.
        smtp_server (str, optional): SMTP server host. If None, read from
            NOTIFY_TASK_SMTP_SERVER.
        smtp_port (int, optional): SMTP server port. If None, read from
            NOTIFY_TASK_SMTP_PORT.
        cc (str, optional): Comma-separated CC addresses. If None, read from
            NOTIFY_TASK_CC.

    Returns:
        Callable: A decorator that wraps the target function. The wrapped function will:
            - Execute the original function and return its result on success.
            - On exception, catch the exception, send a failure notification, and return
              the exception's string representation.

    Raises:
        smtplib.SMTPException: If SMTP connection, authentication, or sending fails.
        OSError/FileNotFoundError: If referenced local files in the markdown cannot be
            read when attaching or embedding.
        UnicodeDecodeError: While attaching a file as text if decoding fails (the code
            falls back to binary attachment for such cases, but file I/O may still raise).

    Example:
        @notify_task()
        def my_job(x, y):
            return x + y

        # Calling my_job(1, 2) will send an email titled like:
        # "Task my_job success" and include the result, parameters, and duration.
    """

    sender = sender or os.getenv("NOTIFY_TASK_SENDER")
    password = password or os.getenv("NOTIFY_TASK_PASSWORD")
    receiver = receiver or os.getenv("NOTIFY_TASK_RECEIVER")
    smtp_server = smtp_server or os.getenv("NOTIFY_TASK_SMTP_SERVER")
    smtp_port = smtp_port or os.getenv("NOTIFY_TASK_SMTP_PORT")
    cc = cc or os.getenv("NOTIFY_TASK_CC")

    def wrapper(task):
        @wraps(task)
        def wrapper(*args, **kwargs):
            try:
                success = True
                begin = pd.to_datetime("now")
                result = task(*args, **kwargs)
                end = pd.to_datetime("now")
                duration = end - begin
                if isinstance(result, str):
                    result_str = result
                elif isinstance(result, pd.DataFrame) or isinstance(result, pd.Series):
                    if len(result) > 10:
                        result_str = (
                            result.head().to_markdown()
                            + "\n\n...\n\n"
                            + result.tail().to_markdown()
                        )
                    else:
                        result_str = result.to_markdown()
                elif isinstance(result, dict):
                    result_str = pd.DataFrame(result).to_markdown()
                else:
                    result_str = str(result)
                args = [
                    str(arg).replace(">", "&gt;").replace("<", "&lt;") for arg in args
                ]
                kwargs = {
                    key: str(value).replace(">", "&gt;").replace("<", "&lt;")
                    for key, value in kwargs.items()
                }
                message = (
                    f"{result_str}\n\n"
                    f"> *Parameters: {args} {kwargs}*\n\n"
                    f"> *Run from {begin} to {end} ({duration})*"
                )
            except Exception as e:
                success = False
                result = str(e)
                end = pd.to_datetime("now")
                args = [
                    str(arg).replace(">", "&gt;").replace("<", "&lt;") for arg in args
                ]
                kwargs = {
                    key: str(value).replace(">", "&gt;").replace("<", "&lt;")
                    for key, value in kwargs.items()
                }
                duration = end - begin
                message = (
                    "```\n{traces}\n```\n\n"
                    "> *Parameters: {args} {kwargs}*\n\n"
                    "> *Run from {begin} to {end} ({duration})*"
                ).format(
                    traces="\n".join(
                        [
                            trace.replace("^", "")
                            for trace in traceback.format_exception(
                                type(e), e, e.__traceback__
                            )
                        ]
                    ),
                    args=args,
                    kwargs=kwargs,
                    begin=begin,
                    end=end,
                    duration=duration,
                )
            finally:
                subject = f"Task {task.__name__} {'success' if success else 'failure'}"
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
                server.login(sender, password)
                content = MIMEMultipart("related")
                content["From"] = sender
                content["To"] = receiver
                if cc:
                    content["Cc"] = cc
                content["Subject"] = subject
                html_body = markdown.markdown(
                    message, extensions=["tables", "fenced_code", "codehilite", "extra"]
                )
                # Find all paths in the markdown using a regular expression
                file_paths = re.findall(r"!\[.*?\]\((.*?)\)", message)

                # Attach images and files as needed
                for i, file_path in enumerate(file_paths):
                    file = Path(file_path)
                    if file.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
                        with file.open("rb") as img:
                            img_data = img.read()
                            # Create a unique content ID
                            cid = f"image{i}"
                            image_mime = MIMEImage(img_data)
                            image_mime.add_header("Content-ID", f"<{cid}>")
                            image_mime.add_header(
                                "Content-Disposition", "inline", filename=file.name
                            )
                            content.attach(image_mime)
                            # Replace the file path in the HTML body with a cid reference
                            html_body = html_body.replace(file_path, f"cid:{cid}")
                    else:
                        try:
                            part = MIMEText(file.read_text("utf-8"), "plain", "utf-8")
                            part.add_header(
                                "Content-Disposition",
                                f"attachment; filename={file.name}",
                            )
                            content.attach(part)
                        except UnicodeDecodeError:
                            part = MIMEBase("application", "octet-stream")
                            part.set_payload(file.read_bytes())
                            encoders.encode_base64(part)
                            part.add_header(
                                "Content-Disposition",
                                f"attachment; filename={file.name}",
                            )
                            content.attach(part)

                # Update the HTML part with embedded image references
                content.attach(MIMEText(html_body, "html"))

                # Prepare the recipient list, including CC recipients
                recipient_list = receiver.split(",")
                if cc:
                    recipient_list += cc.split(",")
                server.sendmail(sender, recipient_list, content.as_string())

            return result

        return wrapper

    return wrapper


@retry(exceptions=(requests.exceptions.RequestException,), tries=5, delay=1, backoff=2)
def proxy_request(
    url: str,
    method: str = "GET",
    proxies: Union[dict, list] = None,
    delay: float = 1,
    **kwargs,
) -> requests.Response:
    """Request a URL using an optional list of proxy configurations, falling back to a direct request.

    This function will attempt to perform an HTTP request using each provided proxy in turn.
    If a proxy attempt raises a requests.exceptions.RequestException, it will wait `delay`
    seconds and try the next proxy. If all proxies fail (or if no proxies are provided),
    a direct request (no proxy) is attempted. The function raises if the final request
    fails; note that the retry decorator will retry the whole function on RequestException.

    Args:
        url (str): Target URL.
        method (str, optional): HTTP method to use (e.g., "GET", "POST"). Defaults to "GET".
        proxies (dict or list[dict] or None, optional): A single requests-style proxies dict
            (e.g. {"http": "...", "https": "..."}) or a list of such dicts. If None, no proxies
            will be tried. Defaults to None.
        delay (float, optional): Seconds to sleep between proxy attempts on failure. Defaults to 1.
        **kwargs: Additional keyword arguments forwarded to requests.request (e.g., headers, data).

    Returns:
        requests.Response: The successful requests Response object.

    Raises:
        requests.exceptions.RequestException: If the final request (after trying proxies and direct)
            fails. Note that the retry decorator may re-invoke this function on such exceptions.
    """
    # Normalize proxies into a list of dicts
    if proxies is None:
        proxy_list = []
    elif isinstance(proxies, dict):
        proxy_list = [proxies]
    elif isinstance(proxies, list):
        proxy_list = proxies.copy()
    else:
        # Accept any iterable of proxy dicts (e.g., tuple)
        proxy_list = list(proxies)

    # Use a deepcopy to avoid mutating caller data
    proxy_list = deepcopy(proxy_list)

    for proxy in proxy_list:
        try:
            response = requests.request(method=method, url=url, proxies=proxy, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException:
            time.sleep(delay)

    # Try a direct request if proxies are exhausted or none provided
    response = requests.request(method=method, url=url, **kwargs)
    response.raise_for_status()
    return response


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
        db_path: str = None,
        threads: Optional[int] = None,
    ):
        """Initializes the DuckParquet object.

        Args:
            dataset_path (str): Directory path that stores the parquet dataset.
            name (Optional[str]): The view name. Defaults to directory basename.
            db_path (str): Path to DuckDB database file. Defaults to in-memory.
            threads (Optional[int]): Number of threads used for partition operations.

        Raises:
            ValueError: If the dataset_path is not a directory.
        """
        self.dataset_path = os.path.abspath(dataset_path)
        if not os.path.exists(self.dataset_path):
            os.makedirs(self.dataset_path)
        if not os.path.isdir(self.dataset_path):
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

    # --- Private Helper Methods ---

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
    def _default_view_name(path: str) -> str:
        """Generate a default DuckDB view name from file/directory name.

        Args:
            path (str): Directory or parquet file path.

        Returns:
            str: Default view name.
        """
        base = os.path.basename(path.rstrip(os.sep))
        name = os.path.splitext(base)[0] if base.endswith(".parquet") else base
        if not DuckParquet._is_identifier(name):
            name = "ds_" + re.sub(r"[^A-Za-z0-9_]+", "_", name)
        return name or "dataset"

    @staticmethod
    def _infer_scan_pattern(path: str) -> str:
        """Infer DuckDB's parquet_scan path glob based on the directory path.

        Args:
            path (str): Target directory.

        Returns:
            str: Glob scan pattern.
        """
        if os.path.isdir(path):
            return os.path.join(path, "**/*.parquet")
        return path

    @staticmethod
    def _local_tempdir(target_dir, prefix="__parquet_rewrite_"):
        """Generate a temporary directory for atomic operations under target_dir.

        Args:
            target_dir (str): Directory for temp.

        Returns:
            str: Path to temp directory.
        """
        tmpdir = os.path.join(target_dir, f"{prefix}{uuid.uuid4().hex[:8]}")
        os.makedirs(tmpdir)
        return tmpdir

    def _parquet_files_exist(self) -> bool:
        """Check if there are any parquet files under the dataset path.

        Returns:
            bool: True if any parquet exists, else False.
        """
        for root, dirs, files in os.walk(self.dataset_path):
            for fn in files:
                if fn.endswith(".parquet"):
                    return True
        return False

    def _create_or_replace_view(self):
        """Create or replace the DuckDB view for current dataset."""
        view_ident = DuckParquet._quote_ident(self.view_name)
        sql = f"CREATE OR REPLACE VIEW {view_ident} AS SELECT * FROM parquet_scan('{self.scan_pattern}', HIVE_PARTITIONING=1)"
        self.con.execute(sql)

    def _base_columns(self) -> List[str]:
        """Get all base columns from current parquet duckdb view.

        Returns:
            List[str]: List of column names in the schema.
        """
        return self.list_columns()

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

    def _atomic_replace_dir(self, new_dir: str, old_dir: str):
        """Atomically replace a directory's contents.

        Args:
            new_dir (str): Temporary directory with new data.
            old_dir (str): Target directory to replace.
        """
        if os.path.exists(old_dir):
            shutil.rmtree(old_dir)
        os.replace(new_dir, old_dir)

    # ---- Upsert Internal Logic ----

    def _upsert_no_exist(self, df: pd.DataFrame, partition_by: Optional[list]) -> None:
        """Upsert logic branch if no existing parquet files.

        Args:
            df (pd.DataFrame): Raw DataFrame
            partition_by (Optional[list]): Partition columns
        """
        tmpdir = self._local_tempdir(".")
        try:
            self._copy_df_to_dir(
                df,
                target=tmpdir,
                partition_by=partition_by,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if os.path.exists(tmpdir):
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
        tmpdir = self._local_tempdir(".")
        base_cols = self.list_columns()
        all_cols = ", ".join(DuckParquet._quote_ident(c) for c in base_cols)
        key_expr = ", ".join(DuckParquet._quote_ident(k) for k in keys)

        temp_name = f"newdata_{uuid.uuid4().hex[:6]}"
        self.con.register(temp_name, df)

        try:
            if not partition_by:
                out_path = os.path.join(tmpdir, "data_0.parquet")
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
                dst = os.path.join(self.dataset_path, "data_0.parquet")
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(out_path, dst)
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

                for subdir in next(os.walk(tmpdir))[1]:
                    src = os.path.join(tmpdir, subdir)
                    dst = os.path.join(self.dataset_path, subdir)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        else:
                            os.remove(dst)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(src, dst)
        finally:
            try:
                self.con.unregister(temp_name)
            except Exception:
                pass
            try:
                self.con.unregister(parts_tbl)  # type: ignore
            except Exception:
                pass
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)
            self.refresh()

    # --- Context/Resource Management ---

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

    # --- Public Query/Mutation Methods ---

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
        if os.path.isfile(self.dataset_path):
            pass
        view_ident = DuckParquet._quote_ident(self.view_name)
        base_cols = self._base_columns()
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
        tmpdir = self._local_tempdir(".")
        try:
            self._copy_select_to_dir(
                select_sql,
                target_dir=tmpdir,
                partition_by=partition_by,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)
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
        tmpdir = self._local_tempdir(".")
        try:
            self._copy_select_to_dir(
                select_sql,
                target_dir=tmpdir,
                partition_by=partition_by,
                params=bind_params,
            )
            self._atomic_replace_dir(tmpdir, self.dataset_path)
        finally:
            if os.path.exists(tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)
        self.refresh()


class Collection:
    """Manage an LLM agent knowledge store backed by a persistent Chroma vector database and OpenAI-compatible embeddings.

    This class provides convenience methods to ingest text files, split them into chunks, compute embeddings,
    store and retrieve vectors from a persistent Chroma instance, and optionally apply an LLM-based reranker.
    It centralizes configuration for embedding and reranking models, vector DB path, chunking behavior, and logging.

    Attributes:
        default_collection (str): Default collection name used when none is provided to load/search methods.
        embedding_model (Optional[str]): Name of the embedding model used to compute embeddings.
        chunk_size (int): Maximum number of characters per chunk when splitting documents.
        chunk_overlap (int): Number of characters overlapping between adjacent chunks.
        retrieval_top_k (int): Default number of top vector search results to return.
        reranker_model (Optional[str]): Optional model name for LLM-based reranking. When None, reranking is disabled.
        rerank_top_k (int): Number of documents to keep after reranking (or used as reranker top_n).
        _vector_db_path (str): Filesystem path where the Chroma persistent database is stored.
        _chroma (chromadb.PersistentClient): Underlying persistent Chroma client instance.
        collections (Dict[str, _ChromaVectorStore]): In-memory map of collection name to _ChromaVectorStore wrappers.
        _rerank_fn (Optional[Callable]): Internal callable performing reranking when configured.
        logger: Logger instance used for informational and error messages.

    Example:
        >>> col = Collection(default_collection="notes", embedding_model="text-embedding-3-small", vector_db_path=".kb")
        >>> col.load_knowledge("/path/to/docs")
        >>> results = col.search_knowledge("How to configure the system?")
    """

    class _ChromaVectorStore:

        def __init__(
            self, client: "chromadb.PersistentClient", name: str, embed_fn: Callable
        ):
            """Initialize an internal Chroma-backed vector store wrapper.

            Args:
                client (chromadb.PersistentClient): Chroma persistent client instance used to create/get collections.
                name (str): Name of the Chroma collection to manage.
                embed_fn (Callable): Callable that takes a list of strings and returns list of embeddings.
            """
            self.collection = client.get_or_create_collection(name=name)
            self.embed_fn = embed_fn

        def __len__(self):
            """Return the number of items stored in the underlying Chroma collection.

            Returns:
                int: Number of documents in the collection. Returns 0 if the count cannot be retrieved.
            """
            try:
                return self.collection.count()
            except Exception:
                return 0

        def add_texts(self, texts, metadatas=None):
            """Add a list of text documents with optional metadata into the collection.

            The function will generate stable ids for documents based on metadata 'source'
            and 'chunk_index' if provided, compute embeddings via the embed_fn, and upsert
            documents into the Chroma collection.

            Args:
                texts (Iterable[str]): Iterable of text chunks to insert.
                metadatas (Optional[Iterable[dict]]): Iterable of metadata dicts corresponding to each text.
                    If not provided, empty metadata dicts will be used.

            Returns:
                int: Number of texts added.
            """
            if metadatas is None:
                metadatas = [{} for _ in texts]
            ids = []
            for i, m in enumerate(metadatas):
                src = m.get("source", "unknown")
                idx = m.get("chunk_index", i)
                ids.append(f"{src}::chunk::{idx}")
            vecs = self.embed_fn(texts)
            self.collection.upsert(
                documents=texts, embeddings=vecs, metadatas=metadatas, ids=ids
            )
            return len(texts)

        def search(self, query, k=5):
            """Search the collection for documents most similar to the query.

            Embeds the query with embed_fn, performs a Chroma nearest-neighbor query and
            converts Chroma distances into heuristic similarity scores (1.0 - distance).

            Args:
                query (str): Query string to search for.
                k (int): Number of top results to return.

            Returns:
                List[Tuple[str, dict, float]]: A list of tuples (document_text, metadata, score).
            """
            q_emb = self.embed_fn([query])[0]
            res = self.collection.query(query_embeddings=[q_emb], n_results=k)
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            results = []
            for doc, meta, dist in zip(docs, metas, dists):
                score = 1.0 - float(dist)
                results.append((doc, meta, score))
            return results

    def __init__(
        self,
        default_collection: str = "default",
        base_url: str = None,
        api_key: str = None,
        embedding_model: str = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        retrieval_top_k: int = 5,
        vector_db_path: str = None,
        reranker_model: Optional[str] = None,
        rerank_top_k: Optional[int] = None,
        log_level: str = "INFO",
        log_file: Union[str, Path] = None,
    ):
        """Initialize a Collection used as an LLM agent knowledge store backed by Chroma and OpenAI embeddings.

        This constructor sets up the OpenAI client, embedding model, persistent Chroma client,
        local collections map, optional LLM reranker, and logging.

        Args:
            default_collection (str): Default collection name to use for loading and searching knowledge.
            base_url (Optional[str]): Base URL for the OpenAI-compatible API. If None, read from LITELLM_BASE_URL env.
            api_key (Optional[str]): API key for the OpenAI-compatible API. If None, read from LITELLM_API_KEY env.
            embedding_model (Optional[str]): Embedding model name. If None, read from LITELLM_EMBEDDING_MODEL env.
            chunk_size (int): Maximum number of characters per text chunk.
            chunk_overlap (int): Overlap size in characters between adjacent chunks.
            retrieval_top_k (int): Number of top vector search results to return by default.
            vector_db_path (Optional[str]): Filesystem path to persist Chroma DB. If None, read from AGENT_VECTOR_DB_PATH env or default '.knowledge'.
            reranker_model (Optional[str]): Optional reranker model name used for LLM-based re-ranking.
            rerank_top_k (Optional[int]): Number of documents to keep after reranking. If None, uses retrieval_top_k.
            log_level (str): Logging level name.
            log_file (Optional[Union[str, Path]]): Optional path to a log file.

        """
        dotenv.load_dotenv()
        try:
            import chromadb
        except:
            raise ImportError(
                'Chroma backend not found, please install with `pip install "parquool[knowledge]"`'
            )
        self.base_url = (
            base_url or os.getenv("LITELLM_BASE_URL") or "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.getenv("LITELLM_API_KEY")
        self.embedding_model = embedding_model or os.getenv("LITELLM_EMBEDDING_MODEL")
        self.default_collection = default_collection
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.retrieval_top_k = retrieval_top_k
        self._vector_db_path = (
            vector_db_path or os.getenv("AGENT_VECTOR_DB_PATH") or ".knowledge"
        )
        self.logger = setup_logger(
            f"Collection({self._vector_db_path})", file=log_file, level=log_level
        )
        self._chroma = chromadb.PersistentClient(path=self._vector_db_path)
        self.collections: Dict[str, Agent._MemoryVectorStore] = {}
        self._hydrate_persistent_collections()
        self._rerank_fn = None
        self.reranker_model = reranker_model or os.getenv("LITELLM_RERANKER_MODEL")
        self.rerank_top_k = rerank_top_k or retrieval_top_k
        self._setup_reranker()

    # ----------------- Vector database / Embeddings basic tools -----------------

    def _hydrate_persistent_collections(self):
        """Load existing Chroma collections from the persistent path into the in-memory collections map.

        The method queries the Chroma client for collections and wraps each into _ChromaVectorStore
        using the configured embedding function. Failures are logged and swallowed.
        """
        try:
            existing = self._chroma.list_collections()
            for coll in existing:
                name = getattr(coll, "name", None)
                if not name:
                    continue
                self.collections[name] = self._ChromaVectorStore(
                    client=self._chroma,
                    name=name,
                    embed_fn=self._embed_texts,
                )
            self.logger.info(
                f"Hydrated {len(self.collections)} collections from '{self._vector_db_path}'."
            )
        except Exception as e:
            self.logger.warning(f"Failed to hydrate Chroma collections: {e}")

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Compute embeddings for a list of texts using the configured OpenAI-compatible embedding client.

        Args:
            texts (List[str]): List of input strings to embed.

        Returns:
            List[List[float]]: List of embedding vectors corresponding to each input.

        Raises:
            Exception: Re-raises any underlying embedding error after logging.
        """
        if not texts:
            return []
        try:
            resp = litellm.embedding(
                model=self.embedding_model,
                input=texts,
                api_base=self.base_url,
                api_key=self.api_key,
            )
            return [d["embedding"] for d in resp.data]
        except Exception as e:
            self.logger.error(f"Embedding failed: {e}")
            raise

    def _get_or_create_collection(self, collection_name: str):
        """Get an existing in-memory collection wrapper or create a new one backed by Chroma.

        Args:
            collection_name (str): Name of the collection to fetch or create.

        Returns:
            _ChromaVectorStore: Wrapper instance for the requested collection.
        """
        store = self.collections.get(collection_name)
        if store:
            return store
        store = self._ChromaVectorStore(
            client=self._chroma,
            name=collection_name,
            embed_fn=self._embed_texts,
        )
        self.collections[collection_name] = store
        return store

    def _split_text(self, text: str) -> List[str]:
        """Split a long text into chunks according to configured chunk_size and chunk_overlap.

        Chunks are created by sliding a fixed-size window with configured overlap. Empty or whitespace-only
        chunks are ignored.

        Args:
            text (str): Input text to split.

        Returns:
            List[str]: List of non-empty text chunks.
        """
        text = text.strip()
        if not text:
            return []
        chunks = []
        n = len(text)
        step = max(1, self.chunk_size - self.chunk_overlap)
        for start in range(0, n, step):
            end = min(n, start + self.chunk_size)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= n:
                break
        return chunks

    def _read_file_text(self, path: Path) -> str:
        """Read textual content from a file path for supported file types.

        Supported plain-text-like suffixes are read directly. For PDF and DOCX, optional libraries
        (pypdf and python-docx) are used where available. Unsupported binary files are skipped.

        Args:
            path (Path): Filesystem path to read.

        Returns:
            str: Extracted text. Empty string if reading fails or file type is unsupported.
        """
        suffix = path.suffix.lower()
        # Pure text
        text_like = {
            ".txt",
            ".md",
            ".rst",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".tsv",
            ".xml",
            ".html",
            ".htm",
            ".ini",
            ".cfg",
            ".toml",
            ".log",
        }
        if suffix in text_like:
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                self.logger.warning(f"Failed to read {path}: {e}")
                return ""

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                pages = [p.extract_text() or "" for p in reader.pages]
                return "\n".join(pages)
            except Exception as e:
                self.logger.warning(f"To read PDF install pypdf. Skip {path}: {e}")
                return ""

        if suffix == ".docx":
            try:
                import docx  # python-docx

                doc = docx.Document(str(path))
                return "\n".join([p.text for p in doc.paragraphs])
            except Exception as e:
                self.logger.warning(
                    f"To read DOCX install python-docx. Skip {path}: {e}"
                )
                return ""

        self.logger.info(f"Skip non-text file: {path}")
        return ""

    def _setup_reranker(self):
        """Configure an optional LLM-based reranking function if a reranker model is provided.

        The configured rerank function will call litellm.rerank with the configured model and
        normalize the returned results into a list of {"index": int, "score": float} items.
        If no reranker_model is set, the method is a no-op.
        """
        if not self.reranker_model:
            self.logger.debug("No reranker model configured; skip reranking.")
            return

        def _llm_rerank(
            query: str, docs: List[str], metas: List[Dict], top_n: Optional[int] = None
        ):
            if not docs:
                return []
            top_n = min(top_n or len(docs), len(docs))

            data = litellm.rerank(
                model=self.reranker_model,
                query=query,
                documents=docs,
                top_n=top_n,
                return_documents=False,
                api_base=self.base_url,
                api_key=self.api_key,
            )

            items = None
            if isinstance(data, dict):
                items = data.get("results")
            if not isinstance(items, list):
                items = data if isinstance(data, list) else []

            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                idx = it.get("index")
                if idx is None:
                    continue
                score = it.get("relevance_score")
                try:
                    idx = int(idx)
                except Exception:
                    continue
                try:
                    score = float(score) if score is not None else None
                except Exception:
                    score = None
                if 0 <= idx < len(docs):
                    out.append({"index": idx, "score": score})

            if out and all(o.get("score") is not None for o in out):
                out.sort(key=lambda x: x["score"], reverse=True)
            return out[:top_n]

        self._rerank_fn = _llm_rerank
        self.logger.info(f"LLM reranker enabled (model={self.reranker_model}).")

    def _normalize_rerank_result(
        self, res: List, n_docs: int
    ) -> List[Tuple[int, Optional[float]]]:
        """Normalize various reranker result formats into a list of (index, score) tuples.

        Accepts integer indices, (index, score) tuples/lists, or dicts with 'index' and optional 'score'.
        Filters out invalid indices and sorts by score descending if all items have scores.

        Args:
            res (List): Raw reranker output in one of several accepted formats.
            n_docs (int): Number of documents that were reranked (used to validate indices).

        Returns:
            List[Tuple[int, Optional[float]]]: Normalized and optionally sorted list of (index, score).
        """
        ranked: List[Tuple[int, Optional[float]]] = []
        if not isinstance(res, list) or not res:
            return ranked
        for item in res:
            idx = None
            score = None
            if isinstance(item, int):
                idx = item
            elif isinstance(item, (tuple, list)) and len(item) >= 1:
                idx = int(item[0])
                if len(item) > 1:
                    try:
                        score = float(item[1])
                    except Exception:
                        score = None
            elif isinstance(item, dict):
                if "index" in item:
                    idx = int(item["index"])
                if item.get("score") is not None:
                    try:
                        score = float(item["score"])
                    except Exception:
                        score = None
            if idx is not None and 0 <= idx < n_docs:
                ranked.append((idx, score))
        if ranked and all(s is not None for _, s in ranked):
            ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def load(
        self,
        path_or_paths: Union[str, Path, List[Union[str, Path]]],
        collection_name: Optional[str] = None,
        recursive: bool = True,
        include_globs: Optional[List[str]] = None,
        exclude_globs: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Load files from one or more paths into the specified collection as vectorized knowledge chunks.

        The method discovers files according to include/exclude glob patterns, reads text from supported files,
        splits texts into chunks, computes embeddings and upserts them to the target collection. It returns
        counts of files and chunks added.

        Args:
            path_or_paths (Union[str, Path, List[Union[str, Path]]]): Single path or list of paths (files or directories).
            collection_name (Optional[str]): Target collection name. Defaults to the instance default_collection.
            recursive (bool): Whether to search directories recursively when applying include_globs.
            include_globs (Optional[List[str]]): List of glob patterns to include. If None, a sensible default list is used.
            exclude_globs (Optional[List[str]]): List of glob patterns to exclude from the discovered files.

        Returns:
            Dict[str, int]: Summary dictionary with keys 'files' and 'chunks' indicating how many files and chunks were loaded.
        """
        collection_name = collection_name or self.default_collection
        store = self._get_or_create_collection(collection_name)

        if isinstance(path_or_paths, (str, Path)):
            paths = [path_or_paths]
        else:
            paths = list(path_or_paths)

        include_globs = include_globs or [
            "**/*.md",
            "**/*.txt",
            "**/*.py",
            "**/*.json",
            "**/*.yaml",
            "**/*.yml",
            "**/*.csv",
            "**/*.tsv",
            "**/*.html",
            "**/*.htm",
            "**/*.log",
            "**/*.rst",
        ]
        exclude_globs = exclude_globs or []

        files: List[Path] = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                for pattern in include_globs:
                    for fp in (
                        p.glob(pattern)
                        if recursive
                        else p.glob(pattern.replace("**/", ""))
                    ):
                        files.append(fp)
            elif p.is_file():
                files.append(p)
            else:
                self.logger.warning(f"Path not found or unsupported: {p}")

        exclude_set = set()
        for pat in exclude_globs:
            for f in list(files):
                if f.match(pat):
                    exclude_set.add(f)
        files = [f for f in files if f not in exclude_set]

        files = sorted(set(files))
        file_count = 0
        chunk_count = 0
        for f in files:
            text = self._read_file_text(f)
            if not text.strip():
                continue
            chunks = self._split_text(text)
            if not chunks:
                continue
            metadatas = [
                {"source": str(f), "chunk_index": i} for i in range(len(chunks))
            ]
            added = store.add_texts(chunks, metadatas)
            if added > 0:
                file_count += 1
                chunk_count += added

        self.logger.info(
            f"Knowledge loaded into collection '{collection_name}': files={file_count}, chunks={chunk_count}"
        )
        return {"files": file_count, "chunks": chunk_count}

    def search(
        self,
        query: str,
        collection_name: Optional[str] = None,
    ) -> List[Dict]:
        """Search the knowledge store for documents relevant to the query, optionally reranking with an LLM.

        Performs vector search in the specified collection and, if configured, reranks top candidates using
        the LLM reranker. Results include text, metadata, vector score, and optional rerank_score.

        Args:
            query (str): Query string to search for.
            collection_name (Optional[str]): Collection name to search. Defaults to the instance default_collection.

        Returns:
            List[Dict]: List of result dictionaries. Each dictionary contains keys:
                - 'text' (str): The document text/chunk.
                - 'metadata' (dict): Associated metadata for the chunk.
                - 'score' (float): Similarity score from the vector store (heuristic).

                - 'rerank_score' (Optional[float]): Optional reranker relevance score when reranking is enabled.
        """
        collection_name = collection_name or self.default_collection
        store = self.collections.get(collection_name)
        if not store or len(store) == 0:
            self.logger.info(f"No knowledge found in collection '{collection_name}'.")
            return []
        hits = store.search(
            query, k=self.retrieval_top_k
        )  # [(text, meta, sim_score), ...]

        if not self._rerank_fn:
            return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]

        try:
            docs = [t for t, _, _ in hits]
            metas = [m for _, m, _ in hits]
            top_n = min(len(docs), self.rerank_top_k or len(docs))

            raw = self._rerank_fn(query, docs, metas, top_n=top_n)
            ranked = self._normalize_rerank_result(raw, n_docs=len(docs))
            if not ranked:
                self.logger.debug(
                    "Reranker returned empty/invalid result; fallback to vector order."
                )
                return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]

            used = set()
            reranked_results: List[Dict] = []
            for idx, rscore in ranked:
                t, m, s = hits[idx]
                reranked_results.append(
                    {"text": t, "metadata": m, "score": s, "rerank_score": rscore}
                )
                used.add(idx)

            for i, (t, m, s) in enumerate(hits):
                if len(reranked_results) >= self.rerank_top_k:
                    break
                if i not in used:
                    reranked_results.append({"text": t, "metadata": m, "score": s})

            return reranked_results[: self.retrieval_top_k]
        except Exception as e:
            self.logger.warning(f"Reranking failed: {e}. Fallback to vector order.")
            return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]


class Agent:
    """
    High-level wrapper that simplifies construction and interaction with an LLM-based agent.

    The Agent wrapper configures an OpenAI-compatible client, logging, optional tracing,
    and constructs an underlying agents.Agent instance. It provides convenient synchronous,
    asynchronous, and streaming run methods that use an SQLite-backed session by default.
    It also supports retrieval-augmented generation (RAG) via an optional Collection, built-in
    helper tools for exporting and retrieving conversations, and a mechanism to expose the
    agent as a tool to other agents.

    Key responsibilities:
      - Load environment configuration and initialize the model client.
      - Configure tracing and logging.
      - Register callable tools and agents-compatible function tools.
      - Provide prompt augmentation using retrieval from a Collection (RAG).
      - Offer run, run_sync, run_streamed, and stream interfaces that persist conversations to SQLite sessions.

    Attributes:
        logger (logging.Logger): Logger configured for this wrapper.
        agent (agents.Agent): Underlying agent instance that performs reasoning, tool calls, and messaging.
        model (LitellmModel): Model client used by the underlying agent.
        model_settings (agents.ModelSettings): Model settings forwarded to the agent.
        tools (dict): Mapping of tool name to callable for convenience tools.
        function_tools (List[agents.Tool]): List of agents-compatible function tools registered on the agent.
        handoff_agents (List[agents.Agent]): List of agents to which the wrapper can hand off control.
        preset_prompts (dict): Optional preset prompts for common tasks.
        collection (Collection | None): Optional knowledge collection used for RAG augmentation.
        rag_prompt_template (str): Template used to format augmented prompts with retrieved context.
        rag_max_context (int): Maximum total length of concatenated context used for RAG.

    Example:
        >>> agent = Agent(model_name="gpt-4", log_level="DEBUG", collection=my_collection)
        >>> result = agent.run("Summarize the conversation.")
    """

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        name: str = "Agent",
        log_file: str = None,
        log_level: str = "INFO",
        model_name: str = None,
        model_settings: dict = None,
        instructions: str = "You are a helpful assistant.",
        preset_prompts: dict = None,
        tools: List[agents.FunctionTool] = None,
        tool_use_behavior: str = "run_llm_again",
        handoffs: List[agents.Agent] = None,
        output_type: str = None,
        input_guardrails: List[agents.InputGuardrail] = None,
        output_guardrails: List[agents.OutputGuardrail] = None,
        default_openai_api: str = "chat_completions",
        trace_disabled: bool = True,
        collection: Collection = None,
        rag_max_context: int = 6000,
        rag_prompt_template: str = None,
        session_id: str = None,
        session_db: Union[Path, str] = ":memory:",
    ):
        """
        Initialize the Agent wrapper, configure OpenAI client, tracing, logging, and set up the underlying agent.

        This initializer:
        - Loads environment variables.
        - Configures OpenAI client based on inputs or environment variables.
        - Enables or disables tracing.
        - Sets up logging based on given log level and file.
        - Creates the internal agents.Agent instance with provided settings.

        Args:
            base_url (str, optional): Base URL for the OpenAI client. Defaults to environment variable LITELLM_BASE_URL if not set.
            api_key (str, optional): API key for the OpenAI client. Defaults to environment variable LITELLM_API_KEY if not set.
            name (str): Name of the agent wrapper and underlying agent.
            log_file (str, optional): Path to file for logging output.
            log_level (str): Logging verbosity level (e.g. "INFO", "DEBUG").
            model_name (str, optional): Name of the model to use. Defaults to environment variable LITELLM_MODEL_NAME if not set.
            model_settings (dict, optional): Additional model configuration forwarded to agents.ModelSettings.
            instructions (str): High-level instructions for the underlying agent.
            preset_prompts (dict, optional): Dictionary of preset prompts for common tasks.
            tools (List[agents.FunctionTool], optional): List of tool descriptors or callables to add to the agent.
            tool_use_behavior (str): Strategy for how tools are used by the agent.
            handoffs (List[agents.Agent], optional): List of handoff agents.
            output_type (str, optional): Optional output type annotation for the agent.
            input_guardrails (List[agents.InputGuardrail], optional): List of input guardrails to enforce.
            output_guardrails (List[agents.OutputGuardrail], optional): List of output guardrails to enforce.
            default_openai_api (str): Default OpenAI API endpoint to use (e.g. "chat_completions").
            trace_disabled (bool): If True, disables tracing features.
            collection (Collection, optional): Knowledge collection for retrieval-augmented generation (RAG).
            rag_max_context (int): Maximum total context length for RAG augmentation.
            rag_prompt_template (str, optional): Template string for prompt augmentation with retrieved context.
            session_id (str, optional): Session ID, if not specified, a uuid-4 string will be applied.
            session_db (str, optional): Path to session database file (sqlite), if not specified, in-memory database will be used.

        Returns:
            None
        """
        dotenv.load_dotenv()
        agents.set_default_openai_api(api=default_openai_api)
        agents.set_tracing_disabled(disabled=trace_disabled)
        self.logger = setup_logger(name, file=log_file, level=log_level)

        self.handoff_agents = []
        for handoff in handoffs or []:
            if isinstance(handoff, Agent):
                self.handoff_agents.append(handoff.agent)
            elif isinstance(handoff, agents.Agent):
                self.handoff_agents.append(handoff)
            else:
                self.logger.warning(
                    "handoffs must be BaseAgent or agents.Agent instances"
                )

        self.function_tools = []
        self.tools = {
            "export_conversation": self.export_conversation,
            "get_conversation": self.get_conversation,
        }
        for fnt in tools or []:
            if isinstance(fnt, agents.Tool):
                self.function_tools.append(fnt)
            elif callable(fnt):
                self.tools[fnt.__name__] = fnt
                self.function_tools.append(agents.function_tool(fnt))
            else:
                self.logger.warning("tools must be agents.Tool or callable instances")

        self.model = LitellmModel(
            base_url=base_url or os.getenv("LITELLM_BASE_URL") or "https://api.openai.com/v1",
            api_key=api_key or os.getenv("LITELLM_API_KEY"),
            model=model_name or os.getenv("LITELLM_MODEL_NAME"),
        )

        model_settings = model_settings or dict()
        if isinstance(model_settings, dict):
            model_settings.update({"include_usage": True})
            self.model_settings = agents.ModelSettings(**model_settings)
        elif isinstance(model_settings, agents.ModelSettings):
            self.model_settings = model_settings
        elif not isinstance(model_settings, agents.ModelSettings):
            self.logger.warning(
                "model_settings must be a dict or agents.ModelSettings instance"
            )

        self.collection = collection
        if not isinstance(self.collection, Collection) and not self.collection is None:
            self.collection = None
            self.logger.warning("collections must be Collection instances")
        self.rag_max_context = rag_max_context

        self.agent = agents.Agent(
            name=name,
            instructions=instructions,
            output_type=output_type,
            tools=self.function_tools,
            tool_use_behavior=tool_use_behavior,
            handoffs=self.handoff_agents,
            model=self.model,
            model_settings=self.model_settings,
            input_guardrails=input_guardrails or list(),
            output_guardrails=output_guardrails or list(),
        )
        self.preset_prompts = preset_prompts or dict()
        self.rag_prompt_template = rag_prompt_template or (
            "You are a helpful assistant. Use the following context to answer the question. "
            "If the context is not sufficient, say you don't know.\n\n"
            "Context:\n{context}\n\n"
            "Question:\n{question}"
        )

        self.session_id = session_id or uuid.uuid4().hex
        self.session_db = session_db
        self.session = agents.SQLiteSession(
            session_id=self.session_id, db_path=self.session_db
        )

    # ----------------- Built-in Tools -----------------

    @staticmethod
    def google_search(
        query: str,
        location: Literal["China", "United States", "Germany", "France"] = None,
        country: str = None,
        language: str = None,
        to_be_searched: str = None,
        start: str = None,
        num: str = None,
    ):
        """
        Google search page result tool. When asked about a question, you can use this tool to get an original google search page result.
        After browsing the search page result, you can pick some of the valuable result links to view by the `read_url` tool.

        Args:
            query (str): Parameter defines the query you want to search.
                You can use anything that you would use in a regular Google search. e.g. inurl:, site:, intitle:.
                We also support advanced search query parameters such as as_dt and as_eq.
            location (str): Parameter defines from where you want the search to originate.
                If several locations match the location requested, we'll pick the most popular one.
                If location is omitted, the search may take on the location of the proxy.
                When only the location parameter is set, Google may still take into account the proxy’s country, which can influence some results.
                For more consistent country-specific filtering, use the `country` parameter alongside location.
            country (str): Parameter defines the country to use for the Google search.
                It's a two-letter country code. (e.g., cn for China, us for the United States, uk for United Kingdom, or fr for France).
                Your country code should be supported by Google countries codes.
            language (str): Parameter defines the language to use for the Google search.
                It's a two-letter language code. (e.g., zh-cn for Chinese(Simplified), en for English, es for Spanish, or fr for French).
                Your language code should be supported by Google languages.
            to_be_searched (str): parameter defines advanced search parameters that aren't possible in the regular query field.
                (e.g., advanced search for patents, dates, news, videos, images, apps, or text contents).
            start (str): Parameter defines the result offset. It skips the given number of results.
                It's used for pagination. (e.g., 0 (default) is the first page of results, 10 is the 2nd page of results, 20 is the 3rd page of results, etc.).
                Google Local Results only accepts multiples of 20 (e.g. 20 for the second page results, 40 for the third page results, etc.) as the start value.
            num (str): Parameter defines the maximum number of results to return.
                (e.g., 10 (default) returns 10 results, 40 returns 40 results, and 100 returns 100 results).
                The use of num may introduce latency, and/or prevent the inclusion of specialized result types.
                It is better to omit this parameter unless it is strictly necessary to increase the number of results per page.
                Results are not guaranteed to have the number of results specified in num.

        Return:
            (str) The search report in markdown format.
        """

        try:
            import serpapi
        except ImportError as e:
            return 'No web search backend found, install by `pip install "parquool[websearch]"`'

        api_keys = [key.strip() for key in os.getenv("SERPAPI_KEY").split(",")]
        random.shuffle(api_keys)
        param_names = ["location", "gl", "hl", "tbs", "start", "num"]
        param_vars = [location, country, language, to_be_searched, start, num]
        params = {"engine": "google", "q": query}
        for name, param in zip(param_names, param_vars):
            if param is not None:
                params[name] = param

        for api_key in api_keys:
            try:
                result = serpapi.search(params, api_key=api_key)
            except Exception as e:
                continue
            result = result.as_dict()
            break

        else:
            return f"Request failed, please check your parameter and try again."

        search_metadata = result["search_metadata"]
        search_report = (
            f"# Search Report for Query {query}\n\n"
            f"Created at {search_metadata['created_at']}, processed at {search_metadata['processed_at']}."
            f"You can get access to json file at {search_metadata['json_endpoint']}, html file at {search_metadata['raw_html_file']}."
            f"{result['search_information']['total_results']} Found. {search_metadata['total_time_taken']} seconds taken.\n\n"
        )
        for ores in result.get("organic_results", []):
            search_report += (
                f"## [{ores['title']}]({ores['link']})\n\n"
                + f"[{ores['source']}] {ores['snippet']}\n\n"
                + (f"> date: {ores['date']}\n" if "date" in ores.keys() else "")
            )
        return search_report

    @staticmethod
    def read_url(
        url_or_urls: Union[str, List],
        engine: Literal["direct", "browser"] = None,
        return_format: Literal["markdown", "html", "text", "screeshot"] = None,
        with_links_summary: Literal["all", "true"] = "true",
        with_image_summary: Literal["all", "true"] = "true",
        retain_image: bool = False,
        do_not_track: bool = True,
        set_cookie: str = None,
        max_length_each: int = 100000,
    ):
        """Fetch and summarize the readable content of one or more URLs via the r.jina.ai reader proxy.

        The agent should call this tool when it needs the actual page text or a snapshot of the page to
        extract facts, quotes, or to decide whether the page is worth further processing.

        Args:
            url_or_urls (Union[str, List]): A single URL string or a list of URL strings to read.
                Provide full URLs as produced by search results (e.g., "https://example.com/page").
            engine (Literal["direct", "browser"], optional): Which fetching engine the proxy
                should use. "direct" performs a direct HTTP fetch, "browser" uses a headless
                browser to render the page (recommended for JS-heavy sites). If omitted, the
                proxy service default is used.
            return_format (Literal["markdown", "html", "text", "screeshot"], optional):
                Desired format of the proxy's returned content:
                - "markdown": proxy attempts to extract and return a clean Markdown version.
                - "html": returns raw or minimally processed HTML.
                - "text": plain text extraction.
                - "screeshot": request an image capture of the page (note the implementation
                currently expects the literal "screeshot").
                If omitted, the proxy service default is used.
            with_links_summary (Literal["all", "true"], optional):
                Wether to summarize all the links in the end of the result page:
                - "all": list all the links in the page and summarize them in the end.
                - "true": list all the unique links in the page and summarize them in the end.
                - None: keep links in-line in result.
            with_image_summary (Literal["all", "true"], optional):
                Wether to summarize all the images in the end of the result page:
                - "all": list all the images in the page and summarize them in the end.
                - "true": list all the unique images in the page and summarize them in the end.
                - None: keep images in-line in result.
            retain_image (bool, optional): If True (default), the returned HTML/Markdown may
                include image references. If False, images are disabled/removed by the proxy.
            do_not_track (bool, optional): If True (default), the header DNT: 1 is sent to
                indicate "do not track" preference to the proxy.
            set_cookie (str, optional): If provided, sets a Cookie header value to be passed
                to the proxy (useful for accessing pages that require a specific cookie).
            max_length_each (int, optional): Maximum number of characters to include from each
                successful response in the returned report. Defaults to 7168. Longer pages will
                be truncated to this length.

        Returns:
            str: A Markdown-formatted report string describing the results for each requested URL.
            The report contains:
            - A summary header with the number of input URLs.
            - "Success Requests" section listing each successful URL and the first
                max_length_each characters of the returned content.
            - "Failure Requests" section listing each URL that failed and the associated
                error message.
        """
        urls = url_or_urls if isinstance(url_or_urls, list) else [url_or_urls]
        headers = {}
        if engine:
            headers["X-Engine"] = engine
        if return_format:
            headers["X-Return-Format"] = return_format
        if with_links_summary:
            headers["X-With-Links-Summary"] = with_links_summary
        if with_image_summary:
            headers["X-With-Images-Summary"] = with_image_summary
        if not retain_image:
            headers["X-Retain-Images"] = "none"
        if do_not_track:
            headers["DNT"] = "1"
        if set_cookie:
            headers["X-Set-Cookie"] = set_cookie
        failure = []
        success = []

        for url in urls:
            try:
                response = requests.get(f"https://r.jina.ai/{url}", headers=headers)
                response.raise_for_status()
                success.append((url, response.text[:max_length_each]))
            except Exception as e:
                failure.append((url, str(e)))

        read_report = f"# Read results for {len(urls)}\n\n"
        read_report += "## Success Resquests\n\n"
        for suc in success:
            read_report += f"### {suc[0]}\n\n{suc[1]}"

        read_report += "## Failure Resquests\n\n"
        for fai in failure:
            read_report += f"### {fai[0]}\n\n{fai[1]}"

        return read_report

    # ----------------- Internal helpers -----------------

    def __str__(self):
        return str(self.agent)

    def __repr__(self):
        return self.__str__()

    # ----------------- Internal helpers -----------------

    def _build_context_from_hits(self, hits: List[Dict]) -> str:
        """
        Build a concatenated context string from a list of knowledge base search hits.

        This limits the total length of the accumulated context to self.rag_max_context.

        Args:
            hits (List[Dict]): List of knowledge search result documents.

        Returns:
            str: Concatenated context string constructed from the hits.
        """
        if not hits:
            return ""
        parts = []
        total = 0
        for h in hits:
            src = h.get("metadata", {}).get("source", "unknown")
            snippet = h["text"].strip().replace("\n", " ").strip()
            piece = f"[source: {src}]\n{snippet}\n"
            if total + len(piece) > self.rag_max_context:
                break
            parts.append(piece)
            total += len(piece)
        return "\n".join(parts)

    def _maybe_augment_prompt(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = False,
        collection_name: Optional[str] = "default",
    ) -> str:
        """
        Conditionally augment the prompt input using retrieval from the knowledge collection.

        If knowledge usage is enabled and a collection is present, the prompt is augmented with
        relevant context retrieved from the collection, formatted according to the RAG template.

        Args:
            prompt (str): Original prompt text.
            use_knowledge (Optional[bool]): Whether to augment prompt using the knowledge base.
            collection_name (Optional[str]): Name of the collection to query in the knowledge base.

        Returns:
            str: Augmented prompt if applicable, otherwise original prompt.
        """
        if self.collection is None or not use_knowledge:
            return prompt

        collection_name = collection_name or self.collection.default_collection

        try:
            hits = self.collection.search(prompt, collection_name=collection_name)
            if not hits:
                return prompt
            context = self._build_context_from_hits(hits)
            if not context.strip():
                return prompt
            aug = self.rag_prompt_template.format(context=context, question=prompt)
            return aug
        except Exception as e:
            self.logger.warning(
                f"RAG augmentation failed, fallback to original prompt. Err: {e}"
            )
            return prompt

    # ----------------- Public interfaces -----------------

    def as_tool(self, tool_name: str, tool_description: str):
        """
        Expose this agent as a tool descriptor compatible with agents.Tool.

        This acts as a wrapper around the underlying agent's as_tool method.

        Args:
            tool_name (str): Name to expose for the tool.
            tool_description (str): Description of the tool's functionality.

        Returns:
            agents.Tool: A Tool descriptor instance for integration with other agents.
        """
        return self.agent.as_tool(
            tool_name=tool_name, tool_description=tool_description
        )

    def export_conversation(self, output_file: str, limit: int = None):
        """
        Export an SQLite session's conversation history to a JSON file.

        Args:
            output_file (str): Path to the JSON file to save the exported conversation.
            limit (int): Limit number of conversation

        Returns:
            None
        """
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(
                self.get_conversation(limit),
                f,
                indent=2,
            )

    def get_conversation(self, limit: int = None):
        """
        Retrieve the conversation history for a given SQLite session.

        Args:
            limit (int): Limit number of conversation

        Returns:
            List[Dict]: List of conversation items in the session.
        """
        return asyncio.run(self.session.get_items(limit))

    async def stream(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ) -> AsyncIterator:
        """
        Asynchronously iterator to run a prompt and process streaming response events.

        Iterates over streamed events emitted by agents.Runner.run_streamed

        Args:
            prompt (str): Prompt text to execute.
            use_knowledge (Optional[bool], optional): Whether to augment prompt with knowledge base context.
            collection_name (Optional[str], optional): Name of the knowledge collection to use.

        Returns:
            None
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )

        result = agents.Runner.run_streamed(
            self.agent,
            prompt_to_run,
            session=self.session,
        )
        async for event in result.stream_events():
            yield event

    # ----------------- Running triggers -----------------

    async def run(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Synchronously run a prompt using the agent inside an SQLite-backed session.

        Defaults to using an ephemeral in-memory SQLite database unless a persistent db_path is provided.

        Args:
            prompt (str): Text prompt to run.
            use_knowledge (Optional[bool], optional): Whether to utilize knowledge base augmentation.
            collection_name (Optional[str], optional): Name of the knowledge collection to query.

        Returns:
            Any: Result from agents.Runner.run execution (implementation-specific).
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        return agents.Runner.run(
            self.agent,
            prompt_to_run,
            session=self.session,
        )

    def run_sync(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Blocking call to run a prompt synchronously using the agent.

        Wraps agents.Runner.run_sync with an SQLite-backed session.

        Args:
            prompt (str): Prompt text to execute.
            use_knowledge (Optional[bool], optional): Flag to enable prompt augmentation.
            collection_name (Optional[str], optional): Knowledge collection name to use for augmentation.

        Returns:
            Any: Result returned by agents.Runner.run_sync (implementation-specific).
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        return agents.Runner.run_sync(
            self.agent,
            prompt_to_run,
            session=self.session,
        )

    async def run_streamed(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Run a prompt with the agent and process the output in a streaming fashion asynchronously.

        This method runs the asynchronous stream internally and processed the yield output from `stream`.

        Args:
            prompt (str): Prompt text to run.
            session_id (str, optional): Optional conversation session ID; generates new UUID if None.
            db_path (str, optional): Path to SQLite DB file; defaults to ":memory:".
            use_knowledge (Optional[bool], optional): Whether to augment prompt from knowledge base.
            collection_name (Optional[str], optional): Name of the knowledge collection.

        Returns:
            None
        """

        events = self.stream(
            prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        async for event in events:
            # We'll print streaming delta if available
            if event.type == "raw_response_event" and isinstance(
                event.data, ResponseTextDeltaEvent
            ):
                print(event.data.delta, end="", flush=True)
            elif event.type == "raw_response_event" and isinstance(
                event.data, ResponseContentPartDoneEvent
            ):
                print()
            elif event.type == "agent_updated_stream_event":
                self.logger.debug(f"Agent updated: {event.new_agent.name}")
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    self.logger.info(
                        f"<TOOL_CALL> {event.item.raw_item.name}(arguments: {event.item.raw_item.arguments})"
                    )
                elif event.item.type == "tool_call_output_item":
                    self.logger.info(f"<TOOL_OUTPUT> {event.item.output}")
                elif event.item.type == "message_output_item":
                    self.logger.info(
                        f"<MESSAGE> {agents.ItemHelpers.text_message_output(event.item)}"
                    )
                else:
                    pass

    def run_streamed_sync(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Run a prompt with the agent and process the output in a streaming fashion synchronously.

        Args:
            prompt (str): Prompt text to run.
            session_id (str, optional): Optional conversation session ID; generates new UUID if None.
            db_path (str, optional): Path to SQLite DB file; defaults to ":memory:".
            use_knowledge (Optional[bool], optional): Whether to augment prompt from knowledge base.
            collection_name (Optional[str], optional): Name of the knowledge collection.

        Returns:
            None
        """
        asyncio.run(
            self.run_streamed(
                prompt=prompt,
                use_knowledge=use_knowledge,
                collection_name=collection_name,
            )
        )
