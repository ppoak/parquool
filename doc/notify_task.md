## Function `notify_task`

- Module: `parquool.util`
- Qualname: `notify_task`

### Signature

```python
def notify_task(sender: str = None, password: str = None, receiver: str = None, smtp_server: str = None, smtp_port: int = None, cc: str = None)
```

### Summary
Decorator that runs a task and sends an email notification with its result.

### Description
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

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `sender` | `str` | no |  | Sender email address. If None, read from NOTIFY_TASK_SENDER. |
| `password` | `str` | no |  | Sender email password or app-specific password. If None, read from NOTIFY_TASK_PASSWORD. |
| `receiver` | `str` | no |  | Comma-separated recipient addresses. If None, read from NOTIFY_TASK_RECEIVER. |
| `smtp_server` | `str` | no |  | SMTP server host. If None, read from NOTIFY_TASK_SMTP_SERVER. |
| `smtp_port` | `int` | no |  | SMTP server port. If None, read from NOTIFY_TASK_SMTP_PORT. |
| `cc` | `str` | no |  | Comma-separated CC addresses. If None, read from NOTIFY_TASK_CC. |

### Returns

- Type: `Callable`
- Description: A decorator that wraps the target function. The wrapped function will: - Execute the original function and return its result on success. - On exception, catch the exception, send a failure notification, and return the exception's string representation.

### Raises

- `smtplib.SMTPException`: If SMTP connection, authentication, or sending fails. OSError/FileNotFoundError: If referenced local files in the markdown cannot be read when attaching or embedding.
- `UnicodeDecodeError`: While attaching a file as text if decoding fails (the code falls back to binary attachment for such cases, but file I/O may still raise).
- `Example`:  @notify_task() def my_job(x, y): return x + y # Calling my_job(1, 2) will send an email titled like: # "Task my_job success" and include the result, parameters, and duration.
