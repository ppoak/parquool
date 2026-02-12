## Function `google_search`

- Module: `parquool.util`
- Qualname: `google_search`

### Signature

```python
def google_search(query: str, location: Literal['China', 'United States', 'Germany', 'France'] = None, country: str = None, language: str = None, to_be_searched: str = None, start: str = None, num: str = None)
```

### Summary
Google search page result tool. When asked about a question, you can use this tool to get an original google search page result. After browsing the search page result, you can pick some of the valuable result links to view by the `read_url` tool.

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `query` | `str` | yes |  | Parameter defines the query you want to search. You can use anything that you would use in a regular Google search. e.g. inurl:, site:, intitle:. We also support advanced search query parameters such as as_dt and as_eq. |
| `location` | `Literal` | no |  | Parameter defines from where you want the search to originate. If several locations match the location requested, we'll pick the most popular one. If location is omitted, the search may take on the location of the proxy. When only the location parameter is set, Google may still take into account the proxy’s country, which can influence some results. For more consistent country-specific filtering, use the `country` parameter alongside location. |
| `country` | `str` | no |  | Parameter defines the country to use for the Google search. It's a two-letter country code. (e.g., cn for China, us for the United States, uk for United Kingdom, or fr for France). Your country code should be supported by Google countries codes. |
| `language` | `str` | no |  | Parameter defines the language to use for the Google search. It's a two-letter language code. (e.g., zh-cn for Chinese(Simplified), en for English, es for Spanish, or fr for French). Your language code should be supported by Google languages. |
| `to_be_searched` | `str` | no |  | parameter defines advanced search parameters that aren't possible in the regular query field. (e.g., advanced search for patents, dates, news, videos, images, apps, or text contents). |
| `start` | `str` | no |  | Parameter defines the result offset. It skips the given number of results. It's used for pagination. (e.g., 0 (default) is the first page of results, 10 is the 2nd page of results, 20 is the 3rd page of results, etc.). Google Local Results only accepts multiples of 20 (e.g. 20 for the second page results, 40 for the third page results, etc.) as the start value. |
| `num` | `str` | no |  | Parameter defines the maximum number of results to return. (e.g., 10 (default) returns 10 results, 40 returns 40 results, and 100 returns 100 results). The use of num may introduce latency, and/or prevent the inclusion of specialized result types. It is better to omit this parameter unless it is strictly necessary to increase the number of results per page. Results are not guaranteed to have the number of results specified in num. |

### Returns

- Type: `any`
