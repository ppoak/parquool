import asyncio
import os
import re
import shutil
import subprocess
import time
import traceback
import uuid
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

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
import openai
import requests
import markdown
import duckdb
import pandas as pd
from retry import retry
from openai.types.responses import ResponseTextDeltaEvent


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
                # 按str或数字
                if isinstance(v, str):
                    in_vals.append(f"'{v}'")
                else:
                    in_vals.append(str(v))
            pivot_on += f" IN ({', '.join(in_vals)})"

        # PIVOT USING
        pivot_using = f"{aggfunc}({DuckParquet._quote_ident(values)})"

        # PIVOT 语句
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


class BaseAgent:
    """High-level wrapper around the internal `agents.Agent` providing conveniences
    for initialization, running, streaming, and CLI integration.

    This class sets up the OpenAI client and tracing defaults, configures logging,
    and exposes synchronous, asynchronous, and streamed run methods that use an
    SQLite-backed session by default.

    Attributes:
        logger: Logger instance used by the wrapper.
        agent: Underlying agents.Agent instance that executes prompts and tools.
    """

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        name: str = "pqagent",
        log_file: str = None,
        log_level: str = "INFO",
        model_name: str = None,
        model_settings: dict = None,
        instructions: str = "You are a helpful assistant.",
        preset_prompts: dict = None,
        tools: list[agents.Tool] = None,
        tool_use_behavior: str = "run_llm_again",
        handoffs: list[agents.Agent] = None,
        output_type: str = None,
        input_guardrails: list[agents.InputGuardrail] = None,
        output_guardrails: list[agents.OutputGuardrail] = None,
        default_openai_api: str = "chat_completions",
        use_model_training: bool = False,
        trace_disabled: bool = True,
    ):
        """Create and configure an Agent wrapper.

        This initializer:
        - Loads environment variables.
        - Configures the default OpenAI client and API mode.
        - Enables/disables tracing.
        - Sets up logging.
        - Constructs the underlying agents.Agent with the provided settings.

        Args:
            base_url: Optional base URL for the OpenAI client. Falls back to OPENAI_BASE_URL env var.
            api_key: Optional API key for the OpenAI client. Falls back to OPENAI_API_KEY env var.
            name: Name for this agent wrapper and the underlying agent.
            log_file: File path to write logs to.
            log_level: Logging level (e.g. "INFO", "DEBUG").
            model_name: Name of the model to use. Falls back to OPENAI_MODEL_NAME env var.
            model_settings: Additional model configuration forwarded to agents.ModelSettings.
            instructions: High-level instructions passed to the underlying agent.
            preset_prompts: Optional dict of preset prompts for common tasks.
            tools: Optional list of tools available to the agent.
            tool_use_behavior: Strategy for how tools are used by the agent.
            handoffs: Optional list of handoff agents.
            output_type: Optional output type annotation for the underlying agent.
            input_guardrails: Optional list of input guardrails.
            output_guardrails: Optional list of output guardrails.
            default_openai_api: Default OpenAI API mode to use (e.g. "chat_completions").
            use_model_training: If True, the OpenAI client is used for tracing/model training.
            trace_disabled: If True, tracing is disabled.

        Returns:
            None
        """

        dotenv.load_dotenv()
        agents.set_default_openai_client(
            client=openai.AsyncOpenAI(
                base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                api_key=api_key or os.getenv("OPENAI_API_KEY"),
            ),
            use_for_tracing=use_model_training,
        )
        agents.set_default_openai_api(api=default_openai_api)
        agents.set_tracing_disabled(disabled=trace_disabled)
        self.logger = setup_logger(name, file=log_file, level=log_level)

        handoff_agents = []
        for handoff in handoffs or []:
            if not isinstance(handoff, BaseAgent):
                handoff_agents.append(handoff.agent)
            elif isinstance(handoff, agents.Agent):
                handoff_agents.append(handoff)
            else:
                raise TypeError("handoffs must be BaseAgent or agents.Agent instances")
        
        model_settings = model_settings or dict()
        if isinstance(model_settings, dict):
            model_settings = agents.ModelSettings(**model_settings)
        elif not isinstance(model_settings, agents.ModelSettings):
            raise TypeError("model_settings must be a dict or agents.ModelSettings instance")
            
        self.agent = agents.Agent(
            name=name,
            instructions=instructions,
            output_type=output_type,
            tools=tools or [],
            tool_use_behavior=tool_use_behavior,
            handoffs=handoff_agents,
            model=model_name or os.getenv("OPENAI_MODEL_NAME"),
            model_settings=model_settings,
            input_guardrails=input_guardrails or list(),
            output_guardrails=output_guardrails or list(),
        )
        self.preset_prompts = preset_prompts or dict()

    def as_tool(self, tool_name: str, tool_description: str):
        """Expose the underlying agent as a Tool descriptor.

        This is a thin wrapper around agents.Agent.as_tool.

        Args:
            tool_name: Name to expose for the tool.
            tool_description: Description of the tool's behavior.

        Returns:
            A Tool-like descriptor produced by the underlying agent.
        """
        return self.agent.as_tool(
            tool_name=tool_name, tool_description=tool_description
        )

    def run(self, prompt: str, session_id: str = None, db_path: str = None):
        """Synchronously run a prompt using the agent within an SQLite-backed session.

        The session defaults to an ephemeral in-memory SQLite DB unless db_path is provided.

        Args:
            prompt: Prompt text to run.
            session_id: Optional session identifier. If not provided, a new UUID is generated.
            db_path: Optional filesystem path for the SQLite DB. Defaults to ":memory:".

        Returns:
            The result returned by agents.Runner.run (implementation-specific).
        """
        return agents.Runner.run(
            self.agent,
            prompt,
            session=agents.SQLiteSession(
                session_id=session_id or uuid.uuid4().hex, db_path=db_path or ":memory:"
            ),
        )

    def run_sync(self, prompt: str, session_id: str = None, db_path: str = None):
        """Run a prompt synchronously using the agent (blocking).

        This wraps agents.Runner.run_sync and uses an SQLiteSession similar to run().

        Args:
            prompt: Prompt text to run.
            session_id: Optional session identifier. If not provided, a new UUID is generated.
            db_path: Optional filesystem path for the SQLite DB. Defaults to ":memory:".

        Returns:
            The result returned by agents.Runner.run_sync (implementation-specific).
        """
        return agents.Runner.run_sync(
            self.agent,
            prompt,
            session=agents.SQLiteSession(
                session_id=session_id or uuid.uuid4().hex, db_path=db_path or ":memory:"
            ),
        )

    async def run_streamed(
        self, prompt: str, session_id: str = None, db_path: str = None
    ):
        """Run a prompt and process stream events asynchronously.

        The method iterates over the async event stream produced by agents.Runner.run_streamed
        and logs the important events. It intentionally ignores raw response deltas and only
        handles agent updates, tool calls, tool outputs, and message outputs.

        Args:
            prompt: Prompt text to run.
            session_id: Optional session identifier. If not provided, a new UUID is generated.
            db_path: Optional filesystem path for the SQLite DB. Defaults to ":memory:".

        Returns:
            None
        """
        session = agents.SQLiteSession(
            session_id=session_id or uuid.uuid4().hex, db_path=db_path or ":memory:"
        )
        result = agents.Runner.run_streamed(
            self.agent,
            prompt,
            session=session,
        )
        async for event in result.stream_events():
            # We'll ignore the raw responses event deltas
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                print(event.data.delta, end="", flush=True)
            # When the agent updates, print that
            elif event.type == "agent_updated_stream_event":
                self.logger.debug(f"Agent updated: {event.new_agent.name}")
            # When items are generated, print them
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    self.logger.info(
                        f"{'-' * 20} Tool was called: {'-' * 20}\n{event.item.raw_item.name}(arguments: {event.item.raw_item.arguments})"
                    )
                elif event.item.type == "tool_call_output_item":
                    self.logger.info(
                        f"{'-' * 20} Tool output: {'-' * 20} \n{event.item.output}"
                    )
                elif event.item.type == "message_output_item":
                    self.logger.info(
                        f"{'-' * 20} Message output: {'-' * 20}\n {agents.ItemHelpers.text_message_output(event.item)}"
                    )
                else:
                    pass  # Ignore other event types
        return result

    async def acli(
        self, stream: bool = True, session_id: str = None, db_path: str = None
    ):
        """
        Asynchronous interactive CLI entrypoint.

        Supports the following commands:
          - Enter any prompt to ask the Agent a question.
          - Enter a command starting with `/` to invoke a preset prompt, e.g. `/summarize`.
          - Enter a command starting with `!` to execute a local shell command, e.g. `!ls`.
          - Enter `exit` or `quit` to exit the CLI.
          - Commands starting with `#` are reserved for future knowledge management (not implemented).
        Args:
            stream: If True, uses streaming output (async event stream). If False, uses synchronous output.
            session_id: Optional session ID. If None, generates a random session.
            db_path: Optional SQLite DB file path. If None, uses in-memory database.
        Returns:
            None
        """
        session_id = session_id or uuid.uuid4().hex
        db_path = db_path or ":memory:"

        while True:
            try:
                user_input = input(" >>> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if user_input.strip().lower() in {"exit", "quit"}:
                break
            elif user_input.startswith("/"):
                user_input = user_input[1:].strip()
                if user_input in self.preset_prompts:
                    user_input = self.preset_prompts[user_input]
                else:
                    print(f"Unknown preset prompt: {user_input}")
                    continue
            elif user_input.startswith("#"):
                pass  # reserved for future knowledge commands
            elif user_input.startswith("!"):
                user_input = user_input[1:].strip()
                subprocess.run(user_input, shell=True)
                continue
            elif not user_input:
                continue

            result: agents.RunResult
            if stream:
                result = self.run_streamed(
                    prompt=user_input, session_id=session_id, db_path=db_path
                )
            else:
                result = await self.run(
                    prompt=user_input, session_id=session_id, db_path=db_path
                )
                if result.final_output is not None:
                    self.logger.info(result.final_output)

    def cli(self, stream: bool = True, session_id: str = None, db_path: str = None):
        """
        Launch interactive CLI (synchronous, blocking main thread).

        This method wraps the asynchronous acli CLI in asyncio.run(), allowing synchronous invocation.
        Args:
            stream: If True, uses streaming output.
            session_id: Optional session ID.
            db_path: Optional SQLite DB file path.

        Returns:
            None
        """
        asyncio.run(self.acli(stream=stream, session_id=session_id, db_path=db_path))
