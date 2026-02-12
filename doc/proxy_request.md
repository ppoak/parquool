## Function `proxy_request`

- Module: `parquool.util`
- Qualname: `proxy_request`

### Signature

```python
def proxy_request(url: str, method: str = 'GET', proxies: Union[dict, list] = None, delay: float = 1, **kwargs) -> requests.models.Response
```

### Summary
Request a URL using an optional list of proxy configurations, falling back to a direct request.

### Description
This function will attempt to perform an HTTP request using each provided proxy in turn.
If a proxy attempt raises a requests.exceptions.RequestException, it will wait `delay`
seconds and try the next proxy. If all proxies fail (or if no proxies are provided),
a direct request (no proxy) is attempted. The function raises if the final request
fails; note that the retry decorator will retry the whole function on RequestException.

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `url` | `str` | yes |  | Target URL. |
| `method` | `str` | no | `'GET'` | HTTP method to use (e.g., "GET", "POST"). Defaults to "GET". |
| `proxies` | `dict or list` | no |  | A single requests-style proxies dict (e.g. {"http": "...", "https": "..."}) or a list of such dicts. If None, no proxies will be tried. Defaults to None. |
| `delay` | `float` | no | `1` | Seconds to sleep between proxy attempts on failure. Defaults to 1. **kwargs: Additional keyword arguments forwarded to requests.request (e.g., headers, data). |
| `kwargs` | `any` | no |  |  |

### Returns

- Type: `requests.Response`
- Description: The successful requests Response object.

### Raises

- `requests.exceptions.RequestException`: If the final request (after trying proxies and direct) fails. Note that the retry decorator may re-invoke this function on such exceptions.
