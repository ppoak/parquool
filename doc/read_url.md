## Function `read_url`

- Module: `parquool.util`
- Qualname: `read_url`

### Signature

```python
def read_url(url_or_urls: Union[str, List], engine: Literal['direct', 'browser'] = None, return_format: Literal['markdown', 'html', 'text', 'screeshot'] = None, with_links_summary: Literal['all', 'true'] = 'true', with_image_summary: Literal['all', 'true'] = 'true', retain_image: bool = False, do_not_track: bool = True, set_cookie: str = None, max_length_each: int = 100000)
```

### Summary
Fetch and summarize the readable content of one or more URLs via the r.jina.ai reader proxy.

### Description
The agent should call this tool when it needs the actual page text or a snapshot of the page to
extract facts, quotes, or to decide whether the page is worth further processing.

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `url_or_urls` | `str or List` | yes |  | A single URL string or a list of URL strings to read. Provide full URLs as produced by search results (e.g., "https://example.com/page"). |
| `engine` | `Literal` | no |  | Which fetching engine the proxy should use. "direct" performs a direct HTTP fetch, "browser" uses a headless browser to render the page (recommended for JS-heavy sites). If omitted, the proxy service default is used. |
| `return_format` | `Literal` | no |  |  Desired format of the proxy's returned content: - "markdown": proxy attempts to extract and return a clean Markdown version. - "html": returns raw or minimally processed HTML. - "text": plain text extraction. - "screeshot": request an image capture of the page (note the implementation currently expects the literal "screeshot"). If omitted, the proxy service default is used. |
| `with_links_summary` | `Literal` | no | `'true'` |  Wether to summarize all the links in the end of the result page: - "all": list all the links in the page and summarize them in the end. - "true": list all the unique links in the page and summarize them in the end. - None: keep links in-line in result. |
| `with_image_summary` | `Literal` | no | `'true'` |  Wether to summarize all the images in the end of the result page: - "all": list all the images in the page and summarize them in the end. - "true": list all the unique images in the page and summarize them in the end. - None: keep images in-line in result. |
| `retain_image` | `bool` | no | `False` | If True (default), the returned HTML/Markdown may include image references. If False, images are disabled/removed by the proxy. |
| `do_not_track` | `bool` | no | `True` | If True (default), the header DNT: 1 is sent to indicate "do not track" preference to the proxy. |
| `set_cookie` | `str` | no |  | If provided, sets a Cookie header value to be passed to the proxy (useful for accessing pages that require a specific cookie). |
| `max_length_each` | `int` | no | `100000` | Maximum number of characters to include from each successful response in the returned report. Defaults to 7168. Longer pages will be truncated to this length. |

### Returns

- Type: `str`
- Description: A Markdown-formatted report string describing the results for each requested URL. The report contains: - A summary header with the number of input URLs. - "Success Requests" section listing each successful URL and the first max_length_each characters of the returned content. - "Failure Requests" section listing each URL that failed and the associated error message.
