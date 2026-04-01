# Agent Module

The agent module provides a high-level wrapper for openai-agents with built-in RAG (Retrieval-Augmented Generation) support, session management, and MCP (Model Context Protocol) server integration.

## Classes

### Agent

High-level wrapper that simplifies construction and interaction with an LLM-based agent.

```python
from parquool import Agent
```

The Agent wrapper:
- Configures an OpenAI-compatible client with environment variable support
- Provides synchronous, asynchronous, and streaming run methods
- Persists conversations to SQLite sessions by default
- Supports retrieval-augmented generation (RAG) via an optional Collection
- Exposes the agent as a tool to other agents

#### Constructor

```python
Agent(
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
    mcp_servers: Optional[List[amcp.MCPServer]] = None,
    mcp_config: Optional[Dict] = None,
    handoffs: List[agents.Agent] = None,
    output_type: str = None,
    input_guardrails: List[agents.InputGuardrail] = None,
    output_guardrails: List[agents.OutputGuardrail] = None,
    default_openai_api: str = "chat_completions",
    trace_disabled: bool = True,
    collection: Collection = None,
    rag_max_context: int = 6000,
    rag_prompt_template: str = None,
    session_db: Union[Path, str] = ":memory:",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | `str` | `None` | Base URL for OpenAI client |
| `api_key` | `str` | `None` | API key for OpenAI client |
| `name` | `str` | `"Agent"` | Name of the agent |
| `log_file` | `str` | `None` | Path to log file |
| `log_level` | `str` | `"INFO"` | Logging level |
| `model_name` | `str` | `None` | Model name (defaults to OPENAI_MODEL_NAME env or "gpt-5") |
| `model_settings` | `dict` | `None` | Additional model configuration |
| `instructions` | `str` | `"You are a helpful assistant."` | Agent instructions |
| `tools` | `List[agents.FunctionTool]` | `None` | Tool descriptors to add to agent |
| `tool_use_behavior` | `str` | `"run_llm_again"` | Tool use strategy |
| `mcp_servers` | `Optional[List[amcp.MCPServer]]` | `None` | MCP servers to use |
| `mcp_config` | `Optional[Dict]` | `None` | MCP server configuration |
| `handoffs` | `List[agents.Agent]` | `None` | Handoff agents |
| `output_type` | `str` | `None` | Output type annotation |
| `input_guardrails` | `List[agents.InputGuardrail]` | `None` | Input guardrails |
| `output_guardrails` | `List[agents.OutputGuardrail]` | `None` | Output guardrails |
| `default_openai_api` | `str` | `"chat_completions"` | OpenAI API endpoint |
| `trace_disabled` | `bool` | `True` | Disable tracing |
| `collection` | `Collection` | `None` | Knowledge collection for RAG |
| `rag_max_context` | `int` | `6000` | Max context length for RAG |
| `rag_prompt_template` | `str` | `None` | RAG prompt template |
| `session_db` | `Union[Path, str]` | `":memory:"` | SQLite session database path |

#### Methods

##### `run_sync()`

Blocking call to run a prompt synchronously.

```python
def run_sync(
    self,
    prompt: str,
    use_knowledge: Optional[bool] = None,
    collection_name: Optional[str] = None,
    session_id: str = None,
) -> agents.RunResult
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | `str` | Prompt text to execute |
| `use_knowledge` | `Optional[bool]` | Enable knowledge base augmentation |
| `collection_name` | `Optional[str]` | Knowledge collection name |
| `session_id` | `str` | Session ID (generates UUID if None) |

**Returns:** `agents.RunResult`

##### `run()`

Asynchronously run a prompt.

```python
async def run(
    self,
    prompt: str,
    use_knowledge: Optional[bool] = None,
    collection_name: Optional[str] = None,
    session_id: str = None,
) -> agents.RunResult
```

**Returns:** `agents.RunResult`

##### `stream()`

Asynchronously iterate over streaming response events.

```python
async def stream(
    self,
    prompt: str,
    use_knowledge: Optional[bool] = None,
    collection_name: Optional[str] = None,
    session_id: str = None,
) -> AsyncIterator
```

**Returns:** `AsyncIterator` of events

##### `run_streamed()`

Run a prompt with streaming output processed asynchronously, printing deltas to stdout.

```python
async def run_streamed(
    self,
    prompt: str,
    use_knowledge: Optional[bool] = None,
    collection_name: Optional[str] = None,
    session_id: str = None,
) -> agents.RunResult
```

**Returns:** `agents.RunResult`

##### `run_streamed_sync()`

Synchronous version of `run_streamed()`.

```python
def run_streamed_sync(
    self,
    prompt: str,
    use_knowledge: Optional[bool] = None,
    collection_name: Optional[str] = None,
    session_id: str = None,
) -> agents.RunResult
```

**Returns:** `agents.RunResult`

##### `as_tool()`

Expose this agent as a tool descriptor for other agents.

```python
def as_tool(self, tool_name: str, tool_description: str) -> agents.Tool
```

**Returns:** `agents.Tool` descriptor

##### `get_conversation()`

Retrieve conversation history for a session.

```python
def get_conversation(self, session_id: str, limit: int = None) -> List[Dict]
```

**Returns:** `List[Dict]` of conversation items

##### `get_all_conversations()`

Retrieve all conversation session IDs.

```python
def get_all_conversations(self) -> List[str]
```

**Returns:** `List[str]` of session IDs

##### `export_conversation()`

Export conversation history to JSON file.

```python
def export_conversation(self, session_id: str, output_file: str, limit: int = None) -> None
```

#### Static Methods (for use as tools)

##### `Agent.google_search`

Web search tool (static method wrapper).

##### `Agent.read_url`

URL reader tool (static method wrapper).

---

### Collection

Manages a knowledge store backed by ChromaDB and OpenAI-compatible embeddings.

```python
from parquool import Collection
```

Provides:
- Text file loading with automatic chunking
- Embedding computation via OpenAI-compatible API
- Vector storage and search via ChromaDB
- Persistent collection management

#### Constructor

```python
Collection(
    default_collection: str = "default",
    base_url: str = None,
    api_key: str = None,
    embedding_model: str = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    retrieval_top_k: int = 5,
    vector_db_path: str = None,
    log_level: str = "INFO",
    log_file: Union[str, Path] = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `default_collection` | `str` | `"default"` | Default collection name |
| `base_url` | `str` | `None` | OpenAI-compatible API base URL |
| `api_key` | `str` | `None` | API key |
| `embedding_model` | `str` | `None` | Embedding model name |
| `chunk_size` | `int` | `1000` | Maximum characters per chunk |
| `chunk_overlap` | `int` | `200` | Overlap between chunks |
| `retrieval_top_k` | `int` | `5` | Number of top results to return |
| `vector_db_path` | `str` | `None` | ChromaDB persistence path |
| `log_level` | `str` | `"INFO"` | Logging level |
| `log_file` | `Union[str, Path]` | `None` | Log file path |

#### Methods

##### `load()`

Load files into the collection as vectorized knowledge chunks.

```python
def load(
    self,
    path_or_paths: Union[str, Path, List[Union[str, Path]]],
    collection_name: Optional[str] = None,
    recursive: bool = True,
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
) -> Dict[str, int]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `path_or_paths` | `Union[str, Path, List]` | File or directory paths |
| `collection_name` | `Optional[str]` | Target collection name |
| `recursive` | `bool` | Search directories recursively |
| `include_globs` | `Optional[List[str]]` | Glob patterns to include |
| `exclude_globs` | `Optional[List[str]]` | Glob patterns to exclude |

**Returns:** `Dict[str, int]` with keys `'files'` and `'chunks'`

**Supported file types:** txt, md, rst, py, json, yaml, yml, csv, tsv, xml, html, htm, ini, cfg, toml, log, pdf, docx

##### `search()`

Search the knowledge store for relevant documents.

```python
def search(
    self,
    query: str,
    collection_name: Optional[str] = None,
) -> List[Dict]
```

**Returns:** `List[Dict]` with keys `'text'`, `'metadata'`, `'score'`

---

### MCP

A lightweight MCP server wrapper for exposing parquool capabilities.

```python
from parquool import MCP
```

#### Constructor

```python
MCP(name: str = "MCP", instructions: str = None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Server name |
| `instructions` | `str` | System instructions |

#### Methods

##### `run()`

Run the MCP server.

```python
def run(self, transport: str = "stdio")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `str` | Transport type ("stdio" or "sse") |

#### Registered Tools

- `google_search` - Web search via SerpAPI
- `read_url` - Fetch and summarize web pages
- `generate_doc` - Generate documentation for parquool targets

#### Registered Resources

Auto-generated documentation via `auto-doc://` URIs:
- `auto-doc://agent`
- `auto-doc://collection`
- `auto-doc://duckpq`
- `auto-doc://ducktable`
- `auto-doc://generate_usage`
- `auto-doc://google_search`
- `auto-doc://notify_task`
- `auto-doc://proxy_request`
- `auto-doc://read_url`
- `auto-doc://setup_logger`

---

### run_mcp()

CLI entry point for starting the Parquool MCP server.

```python
from parquool import run_mcp
```

**Usage:**
```bash
parquool-mcp                    # Default stdio transport
parquool-mcp --transport sse    # SSE transport
```

---

## Usage Examples

### Basic Agent Usage

```python
from parquool import Agent

# Create agent
agent = Agent(
    name="assistant",
    model_name="gpt-4",
    instructions="You are a helpful data analysis assistant."
)

# Synchronous run
result = agent.run_sync("What is the average sales for Q1 2024?")
print(result.final_output)

# Get conversation history
messages = agent.get_conversation(result.session_id)
```

### Agent with RAG

```python
from parquool import Agent, Collection

# Create knowledge base
collection = Collection(
    default_collection="company_docs",
    embedding_model="text-embedding-3-small"
)

# Load documents
collection.load([
    "/docs/policies.md",
    "/docs/products/",
], recursive=True)

# Create agent with RAG
agent = Agent(
    collection=collection,
    rag_max_context=8000
)

# Agent automatically uses knowledge base
result = agent.run_sync("What is our return policy?")
```

### Agent as Tool for Other Agents

```python
from parquool import Agent

# Create specialized agent
data_agent = Agent(
    name="data_analyst",
    instructions="You analyze data and provide insights."
)

# Expose as tool
main_agent = Agent(
    name="assistant",
    tools=[data_agent.as_tool(
        tool_name="analyze_data",
        tool_description="Analyze data and return insights"
    )]
)
```

### Streaming Output

```python
from parquool import Agent

agent = Agent(model_name="gpt-4")

# Async streaming
async def run_with_stream():
    result = await agent.run_streamed("Explain machine learning")
    return result

# Sync streaming
result = agent.run_streamed_sync("Tell me a story")
```

### MCP Server

```python
from parquool import MCP

# Create and run MCP server
server = MCP(
    name="parquool_data",
    instructions="Data and tools server for parquool"
)
server.run(transport="stdio")
```

### Session Management

```python
from parquool import Agent

agent = Agent(session_db="/tmp/sessions.db")

# Run with specific session
result1 = agent.run_sync("My name is Alice", session_id="user_123")
result2 = agent.run_sync("What is my name?", session_id="user_123")

# List all conversations
all_sessions = agent.get_all_conversations()

# Export conversation
agent.export_conversation("user_123", "/tmp/alice_session.json")
```

### Environment Configuration

```bash
# .env file
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL_NAME=gpt-4
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
AGENT_VECTOR_DB_PATH=.knowledge
```
