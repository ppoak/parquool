## Function `generate_usage`

- Module: `parquool.util`
- Qualname: `generate_usage`

### Signature

```python
def generate_usage(target: object, output_path: Optional[str] = None, *, include_private: bool = False, include_inherited: bool = False, include_properties: bool = True, include_methods: bool = True, method_kinds: tuple[str, ...] = ('instance', 'class', 'static'), method_include: Optional[list[str]] = None, method_exclude: Optional[list[str]] = None, attribute_include: Optional[list[str]] = None, attribute_exclude: Optional[list[str]] = None, sort_methods: Literal['name', 'kind', 'none'] = 'name', render_tables: bool = True, include_signature: bool = True, include_sections: Optional[Literal['summary', 'description', 'attributes', 'methods', 'parameters', 'returns', 'raises', 'examples']] = None, heading_level: int = 2) -> str
```

### Parameters

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `target` | `object` | yes |  |  |
| `output_path` | `Optional[str]` | no |  |  |
| `include_private` | `bool` | no | `False` |  |
| `include_inherited` | `bool` | no | `False` |  |
| `include_properties` | `bool` | no | `True` |  |
| `include_methods` | `bool` | no | `True` |  |
| `method_kinds` | `Tuple[str, Ellipsis]` | no | `('instance', 'class', 'static')` |  |
| `method_include` | `Optional[list]` | no |  |  |
| `method_exclude` | `Optional[list]` | no |  |  |
| `attribute_include` | `Optional[list]` | no |  |  |
| `attribute_exclude` | `Optional[list]` | no |  |  |
| `sort_methods` | `Literal` | no | `'name'` |  |
| `render_tables` | `bool` | no | `True` |  |
| `include_signature` | `bool` | no | `True` |  |
| `include_sections` | `Optional[Literal]` | no |  |  |
| `heading_level` | `int` | no | `2` |  |

### Returns

- Type: `str`
