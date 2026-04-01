# Util Module

The util module provides utility functions for logging, HTTP requests, email notifications, documentation generation, and web search.

## Functions

### setup_logger()

Create and configure a logger with optional stream/file handlers and rotation.

```python
from parquool import setup_logger
```

```python
def setup_logger(
    name: str,
    level: int = logging.INFO,
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
) -> logging.Logger
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | Required | Logger name |
| `level` | `int` | `logging.INFO` | Logging level |
| `replace` | `bool` | `False` | Create new logger even if exists |
| `stream` | `bool` | `True` | Add StreamHandler for console output |
| `file` | `Union[Path, str]` | `None` | File path for file handler |
| `clear` | `bool` | `False` | Truncate file before use |
| `style` | `Union[int, str]` | `1` | Formatter style (1-4) or custom formatter |
| `rotation` | `str` | `None` | Rotation mode ("size" or "time") |
| `max_bytes` | `int` | `10*1024*1024` | Max bytes for size rotation |
| `backup_count` | `int` | `5` (size) / `7` (time) | Number of backup files |
| `when` | `str` | `"midnight"` | Time rotation trigger |
| `interval` | `int` | `1` | Time rotation interval |

**Returns:** `logging.Logger` - The configured logger instance

#### Formatter Styles

| Style | Format |
|-------|--------|
| 1 | `[LEVEL]@[TIME]-[NAME]: MESSAGE` |
| 2 | `[LEVEL]@[TIME]-[NAME]@[MODULE:LINENO]: MESSAGE` |
| 3 | `[LEVEL]@[TIME]-[NAME]@[MODULE:LINENO#FUNC]: MESSAGE` |
| 4 | `[LEVEL]@[TIME]-[NAME]@[MODULE:LINENO#FUNC~PID:THREAD]: MESSAGE` |

**Example:**
```python
logger = setup_logger(
    "my_app",
    level="DEBUG",
    file="/var/log/app.log",
    rotation="size",
    max_bytes=10*1024*1024,
    backup_count=5
)
```

---

### notify_task()

Decorator that runs a task and sends an email notification with its result.

```python
from parquool import notify_task
```

```python
def notify_task(
    sender: str = None,
    password: str = None,
    receiver: str = None,
    smtp_server: str = None,
    smtp_port: int = None,
    cc: str = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `sender` | `str` | Sender email address |
| `password` | `str` | Sender email password or app password |
| `receiver` | `str` | Comma-separated recipient addresses |
| `smtp_server` | `str` | SMTP server host |
| `smtp_port` | `int` | SMTP server port |
| `cc` | `str` | Comma-separated CC addresses |

**Returns:** `Callable` - A decorator that wraps the target function

**Environment Variables:**
- `NOTIFY_TASK_SENDER`
- `NOTIFY_TASK_PASSWORD`
- `NOTIFY_TASK_RECEIVER`
- `NOTIFY_TASK_SMTP_SERVER`
- `NOTIFY_TASK_SMTP_PORT`
- `NOTIFY_TASK_CC`

#### Features

- Sends email on task success or failure
- Converts pandas DataFrame/Series to markdown (head/tail if large)
- Embeds local images (.png, .jpg, .gif) via Content-ID (CID)
- Attaches files as email attachments
- Includes execution time and parameters in email

**Example:**
```python
@notify_task(
    sender="app@example.com",
    password="app_password",
    receiver="admin@example.com",
    smtp_server="smtp.example.com",
    smtp_port=587
)
def daily_etl():
    # ETL processing...
    return {"status": "success", "records": 1000}
```

---

### proxy_request()

HTTP request with proxy failover and retry logic.

```python
from parquool import proxy_request
```

```python
@retry(exceptions=(requests.exceptions.RequestException,), tries=5, delay=1, backoff=2)
def proxy_request(
    url: str,
    method: str = "GET",
    proxies: Union[dict, list] = None,
    delay: float = 1,
    **kwargs,
) -> requests.Response
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | Required | Target URL |
| `method` | `str` | `"GET"` | HTTP method |
| `proxies` | `Union[dict, list]` | `None` | Single proxy dict or list of proxies |
| `delay` | `float` | `1` | Seconds between proxy attempts |
| `**kwargs` | | | Additional arguments for `requests.request` |

**Returns:** `requests.Response` - The successful response object

**Raises:** `requests.exceptions.RequestException` if all requests fail

**Behavior:**
- Tries each proxy in order
- Falls back to direct connection if all proxies fail
- Retry decorator will re-invoke on failure

**Example:**
```python
# Single proxy
response = proxy_request(
    "https://api.example.com/data",
    proxies={"http": "http://proxy1:8080", "https": "http://proxy1:8080"}
)

# Multiple proxies (tried in order)
response = proxy_request(
    "https://api.example.com/data",
    proxies=[
        {"http": "http://proxy1:8080", "https": "http://proxy1:8080"},
        {"http": "http://proxy2:8080", "https": "http://proxy2:8080"},
    ]
)
```

---

### generate_usage()

Generate usage documentation for a class or callable.

```python
from parquool import generate_usage
```

```python
def generate_usage(
    target: object,
    output_path: Optional[str] = None,
    include_private: bool = False,
    include_inherited: bool = False,
    include_properties: bool = True,
    include_methods: bool = True,
    method_kinds: tuple[str, ...] = ("instance", "class", "static"),
    method_include: Optional[list[str]] = None,
    method_exclude: Optional[list[str]] = None,
    attribute_include: Optional[list[str]] = None,
    attribute_exclude: Optional[list[str]] = None,
    sort_methods: Literal["name", "kind", "none"] = "name",
    render_tables: bool = True,
    include_signature: bool = True,
    include_sections: Optional[Literal["summary", "description", "attributes", "methods", "parameters", "returns", "raises", "examples"]] = None,
    heading_level: int = 2,
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `target` | `object` | Required | Class or function to document |
| `output_path` | `Optional[str]` | `None` | File path to save documentation |
| `include_private` | `bool` | `False` | Include private members |
| `include_inherited` | `bool` | `False` | Include inherited members |
| `include_properties` | `bool` | `True` | Include properties |
| `include_methods` | `bool` | `True` | Include methods |
| `method_kinds` | `tuple[str, ...]` | `("instance", "class", "static")` | Method types to include |
| `method_include` | `Optional[list[str]]` | `None` | Explicit method names to include |
| `method_exclude` | `Optional[list[str]]` | `None` | Method names to exclude |
| `attribute_include` | `Optional[list[str]]` | `None` | Attribute names to include |
| `attribute_exclude` | `Optional[list[str]]` | `None` | Attribute names to exclude |
| `sort_methods` | `Literal["name", "kind", "none"]` | `"name"` | How to sort methods |
| `render_tables` | `bool` | `True` | Render sections as tables |
| `include_signature` | `bool` | `True` | Include function signatures |
| `include_sections` | `Optional[list]` | `None` | Sections to include |
| `heading_level` | `int` | `2` | Base heading level |

**Returns:** `str` - Generated markdown documentation

**Example:**
```python
from parquool import generate_usage, DuckTable

# Generate docs for a class
docs = generate_usage(
    DuckTable,
    include_private=False,
    render_tables=True
)
print(docs)

# Save to file
generate_usage(DuckTable, output_path="/docs/ducktable.md")

# Generate docs for a function
docs = generate_usage(google_search)
```

---

### google_search()

Google search via SerpAPI.

```python
from parquool import google_search
```

```python
def google_search(
    query: str,
    location: Literal["China", "United States", "Germany", "France"] = "China",
    country: str = "cn",
    language: str = "zh-cn",
    to_be_searched: Optional[str] = None,
    start: str = "1",
    num: str = "10",
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | Required | Search query |
| `location` | `Literal` | `"China"` | Search location |
| `country` | `str` | `"cn"` | Two-letter country code |
| `language` | `str` | `"zh-cn"` | Two-letter language code |
| `to_be_searched` | `Optional[str]` | `None` | Advanced search parameters |
| `start` | `str` | `"1"` | Result offset for pagination |
| `num` | `str` | `"10"` | Number of results |

**Returns:** `str` - Markdown-formatted search report

**Requires:** `SERPAPI_KEY` environment variable (comma-separated for multiple keys)

**Example:**
```python
# Basic search
results = google_search("python library parquet duckdb")

# Advanced search with location
results = google_search(
    query="machine learning",
    location="United States",
    country="us",
    language="en",
    num="20"
)
```

---

### read_url()

Fetch and summarize web page content via Jina reader proxy.

```python
from parquool import read_url
```

```python
def read_url(
    url_or_urls: Union[str, List],
    engine: Literal["direct", "browser"] = "browser",
    return_format: Literal["markdown", "html", "text", "screeshot"] = "markdown",
    with_links_summary: Literal["all", "true"] = "true",
    with_image_summary: Literal["all", "true"] = "true",
    retain_image: bool = False,
    do_not_track: bool = True,
    set_cookie: Optional[str] = None,
    max_length_each: int = 100000,
) -> str
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url_or_urls` | `Union[str, List]` | Required | Single URL or list of URLs |
| `engine` | `Literal` | `"browser"` | Fetching engine ("direct" or "browser") |
| `return_format` | `Literal` | `"markdown"` | Return format |
| `with_links_summary` | `Literal` | `"true"` | Include links summary |
| `with_image_summary` | `Literal` | `"true"` | Include image summary |
| `retain_image` | `bool` | `False` | Retain image references |
| `do_not_track` | `bool` | `True` | Send DNT header |
| `set_cookie` | `Optional[str]` | `None` | Cookie header value |
| `max_length_each` | `int` | `100000` | Max characters per page |

**Returns:** `str` - Markdown-formatted report with results

**Example:**
```python
# Single URL
content = read_url("https://example.com/article")

# Multiple URLs
results = read_url([
    "https://example.com/page1",
    "https://example.com/page2"
])

# Direct fetch without JavaScript
content = read_url(
    "https://example.com/page",
    engine="direct",
    return_format="markdown"
)
```

---

## Usage Examples

### Logging Setup

```python
from parquool import setup_logger
import logging

# Simple console logging
logger = setup_logger("my_app", level=logging.DEBUG)

# File logging with rotation
logger = setup_logger(
    "my_app",
    level=logging.INFO,
    file="/var/log/app.log",
    rotation="time",
    when="midnight",
    backup_count=7
)

# Multiple handlers
logger = setup_logger(
    "my_app",
    level=logging.DEBUG,
    stream=True,
    file="/var/log/app.log",
    rotation="size",
    max_bytes=50*1024*1024,  # 50MB
    backup_count=3,
    style=2  # Include module and line number
)
```

### Task Notification

```python
from parquool import notify_task
import pandas as pd

@notify_task(
    sender="etl@example.com",
    password="app_password",
    receiver="team@example.com",
    smtp_server="smtp.example.com",
    smtp_port=587
)
def process_sales_data(date: str) -> pd.DataFrame:
    # Process data...
    df = pd.DataFrame({"region": ["US", "EU"], "sales": [1000, 800]})
    return df

# On success: sends email with DataFrame as markdown table
# On failure: sends email with error traceback
result = process_sales_data("2024-01-01")
```

### Web Search and Reading

```python
from parquool import google_search, read_url

# Search for information
search_results = google_search(
    "DuckDB Parquet upsert",
    location="United States",
    num="5"
)

# Read specific pages from search results
pages = read_url([
    "https://duckdb.org/docs/sql/statements/insert",
    "https://github.com/duckdb/duckdb"
])

# Combine search and read
search_results = google_search("parquool python library")
# Then use read_url to fetch specific links from results
```
