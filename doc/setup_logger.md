## Function `setup_logger`

- Module: `parquool.util`
- Qualname: `setup_logger`

### Signature

```python
def setup_logger(name, level: str = 20, replace: bool = False, stream: bool = True, file: Union[pathlib._local.Path, str] = None, clear: bool = False, style: Union[int, str] = 1, rotation: str = None, max_bytes: int = None, backup_count: int = None, when: str = None, interval: int = None) -> logging.Logger
```

### Summary
Create and configure a logger with optional stream/file handlers and rotation.

### Description
This helper creates (or returns) a logging.Logger configured with optional
console (stream) and file handlers. File handlers may use size-based or
time-based rotation. If a logger with the same name already has handlers,
the existing logger is returned unchanged (to avoid duplicate handlers).

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `name` | `any` | yes |  | Name of the logger. |
| `level` | `str` | no | `20` | Logging level (e.g. logging.INFO or 'INFO'). |
| `replace` | `bool` | no | `False` | If True, instantiate a new Logger object even if one exists. If False, use logging.getLogger(name). Default: False. |
| `stream` | `bool` | no | `True` | If True, add a StreamHandler to emit logs to stderr/stdout. Default: True. |
| `file` | `Path or str` | no |  | Path to a file to also write logs to. If provided, a file handler is attached (regular or rotating depending on `rotation`). Default: None. |
| `clear` | `bool` | no | `False` | If True and `file` is provided, truncate the file before use. Default: False. |
| `style` | `int or str` | no | `1` | Select a built-in formatter style by integer (1..4). If not an int matching a built-in style, the value is used directly (e.g. a logging.Formatter instance or a custom format string). Default: 1. |
| `rotation` | `str` | no |  | Rotation mode for the file handler. Supported |
| `max_bytes` | `int` | no |  | Max bytes for size-based rotation. If not provided, defaults to 10 * 1024 * 1024 (10 MB). |
| `backup_count` | `int` | no |  | Number of backup files to keep for rotation. |
| `when` | `str` | no |  | When parameter for time-based rotation (e.g. 'midnight'). Default: "midnight" when rotation == "time". |
| `interval` | `int` | no |  | Interval for time-based rotation (in units defined by `when`). Default: 1. |

### Returns

- Type: `logging.Logger`
- Description: The configured logger instance.
