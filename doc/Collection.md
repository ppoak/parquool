## Class `Collection`

- Module: `parquool.agent`
- Qualname: `Collection`

### Summary
Manage an LLM agent knowledge store backed by a persistent Chroma vector database and OpenAI-compatible embeddings.

### Description
This class provides convenience methods to ingest text files, split them into chunks, compute embeddings,
store and retrieve vectors from a persistent Chroma instance.
It centralizes configuration for embedding, vector DB path, chunking behavior, and logging.

### Attributes

| Name | Type | Description |
| ---- | ---- | ----------- |
| `default_collection` | `str` | Default collection name used when none is provided to load/search methods. |
| `embedding_model` | `Optional[str]` | Name of the embedding model used to compute embeddings. |
| `chunk_size` | `int` | Maximum number of characters per chunk when splitting documents. |
| `chunk_overlap` | `int` | Number of characters overlapping between adjacent chunks. |
| `retrieval_top_k` | `int` | Default number of top vector search results to return. |
| `_vector_db_path` | `str` | Filesystem path where the Chroma persistent database is stored. |
| `_chroma` | `chromadb.PersistentClient` | Underlying persistent Chroma client instance. |
| `collections` | `Dict[str, _ChromaVectorStore]` | In-memory map of collection name to _ChromaVectorStore wrappers. |
| `logger` | `` | Logger instance used for informational and error messages. |

### Examples
    >>> col = Collection(default_collection="notes", embedding_model="text-embedding-3-small", vector_db_path=".kb")
    >>> col.load_knowledge("/path/to/docs")
    >>> results = col.search_knowledge("How to configure the system?")

### Methods

#### `load`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def load(self, path_or_paths: Union[str, pathlib._local.Path, List[Union[str, pathlib._local.Path]]], collection_name: Optional[str] = None, recursive: bool = True, include_globs: Optional[List[str]] = None, exclude_globs: Optional[List[str]] = None) -> Dict[str, int]
```

**Summary**

Load files from one or more paths into the specified collection as vectorized knowledge chunks.

**Description**

The method discovers files according to include/exclude glob patterns, reads text from supported files,
splits texts into chunks, computes embeddings and upserts them to the target collection. It returns
counts of files and chunks added.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `path_or_paths` | `str or Path or List` | yes |  | Single path or list of paths (files or directories). |
| `collection_name` | `Optional[str]` | no |  | Target collection name. Defaults to the instance default_collection. |
| `recursive` | `bool` | no | `True` | Whether to search directories recursively when applying include_globs. |
| `include_globs` | `Optional[List]` | no |  | List of glob patterns to include. If None, a sensible default list is used. |
| `exclude_globs` | `Optional[List]` | no |  | List of glob patterns to exclude from the discovered files. |

**Returns**

- Type: `Dict[str, int]`
- Description: Summary dictionary with keys 'files' and 'chunks' indicating how many files and chunks were loaded.

#### `search`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def search(self, query: str, collection_name: Optional[str] = None) -> List[Dict]
```

**Summary**

Search the knowledge store for documents relevant to the query.

**Description**

Performs vector search in the specified collection.
Results include text, metadata, vector score.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `query` | `str` | yes |  | Query string to search for. |
| `collection_name` | `Optional[str]` | no |  | Collection name to search. Defaults to the instance default_collection. |

**Returns**

- Type: `List[Dict]`
- Description: List of result dictionaries. Each dictionary contains keys: - 'text' (str): The document text/chunk. - 'metadata' (dict): Associated metadata for the chunk. - 'score' (float): Similarity score from the vector store (heuristic).
