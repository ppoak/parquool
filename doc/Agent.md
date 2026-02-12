## Class `Agent`

- Module: `parquool.agent`
- Qualname: `Agent`

### Summary
High-level wrapper that simplifies construction and interaction with an LLM-based agent.

### Description
The Agent wrapper configures an OpenAI-compatible client, logging, optional tracing,
and constructs an underlying agents.Agent instance. It provides convenient synchronous,
asynchronous, and streaming run methods that use an SQLite-backed session by default.
It also supports retrieval-augmented generation (RAG) via an optional Collection, built-in
helper tools for exporting and retrieving conversations, and a mechanism to expose the
agent as a tool to other agents.

Key responsibilities:
  - Load environment configuration and initialize the model client.
  - Configure tracing and logging.
  - Register callable tools and agents-compatible function tools.
  - Provide prompt augmentation using retrieval from a Collection (RAG).
  - Offer run, run_sync, run_streamed, and stream interfaces that persist conversations to SQLite sessions.

### Attributes

| Name | Type | Description |
| ---- | ---- | ----------- |
| `base_url` | `str, optional` | Base URL for the OpenAI client. Defaults to environment variable OPENAI_BASE_URL if not set. |
| `api_key` | `str, optional` | API key for the OpenAI client. Defaults to environment variable OPENAI_API_KEY if not set. |
| `name` | `str` | Name of the agent wrapper and underlying agent. |
| `log_file` | `str, optional` | Path to file for logging output. |
| `log_level` | `str` | Logging verbosity level (e.g. "INFO", "DEBUG"). |
| `model_name` | `str, optional` | Name of the model to use. Defaults to environment variable OPENAI_MODEL_NAME if not set. |
| `model_settings` | `dict, optional` | Additional model configuration forwarded to agents.ModelSettings. |
| `instructions` | `str` | High-level instructions for the underlying agent. |
| `preset_prompts` | `dict, optional` | Dictionary of preset prompts for common tasks. |
| `tools` | `List[agents.FunctionTool], optional` | List of tool descriptors or callables to add to the agent. |
| `tool_use_behavior` | `str` | Strategy for how tools are used by the agent. |
| `handoffs` | `List[agents.Agent], optional` | List of handoff agents. |
| `output_type` | `str, optional` | Optional output type annotation for the agent. |
| `input_guardrails` | `List[agents.InputGuardrail], optional` | List of input guardrails to enforce. |
| `output_guardrails` | `List[agents.OutputGuardrail], optional` | List of output guardrails to enforce. |
| `default_openai_api` | `str` | Default OpenAI API endpoint to use (e.g. "chat_completions"). |
| `trace_disabled` | `bool` | If True, disables tracing features. |
| `collection` | `Collection, optional` | Knowledge collection for retrieval-augmented generation (RAG). |
| `rag_max_context` | `int` | Maximum total context length for RAG augmentation. |
| `rag_prompt_template` | `str, optional` | Template string for prompt augmentation with retrieved context. |
| `session_db` | `str, optional` | Path to session database file (sqlite), if not specified, in-memory database will be used. |

### Examples
    >>> # Set environment variable OPENAI_BASE_URL, OPENAI_API_KEY
    >>> agent = Agent(model_name="gpt-4", log_level="DEBUG", collection=my_collection)
    >>> result = agent.run("Summarize the conversation.")

### Methods

#### `as_tool`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def as_tool(self, tool_name: str, tool_description: str) -> Union[agents.tool.FunctionTool, agents.tool.FileSearchTool, agents.tool.WebSearchTool, agents.tool.ComputerTool, agents.tool.HostedMCPTool, agents.tool.LocalShellTool, agents.tool.ImageGenerationTool, agents.tool.CodeInterpreterTool]
```

**Summary**

Expose this agent as a tool descriptor compatible with agents.Tool.

**Description**

This acts as a wrapper around the underlying agent's as_tool method.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `tool_name` | `str` | yes |  | Name to expose for the tool. |
| `tool_description` | `str` | yes |  | Description of the tool's functionality. |

**Returns**

- Type: `agents.Tool`
- Description: A Tool descriptor instance for integration with other agents.

#### `export_conversation`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def export_conversation(self, session_id: str, output_file: str, limit: int = None)
```

**Summary**

Export an SQLite session's conversation history to a JSON file.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `session_id` | `str` | yes |  |  |
| `output_file` | `str` | yes |  | Path to the JSON file to save the exported conversation. |
| `limit` | `int` | no |  | Limit number of conversation |

**Returns**

- Type: `any`
- Description: None

#### `get_all_conversations`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def get_all_conversations(self) -> List
```

**Returns**

- Type: `List[any]`

#### `get_conversation`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def get_conversation(self, session_id: str, limit: int = None) -> List
```

**Summary**

Retrieve the conversation history for a given SQLite session.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `session_id` | `str` | yes |  |  |
| `limit` | `int` | no |  | Limit number of conversation |

**Returns**

- Type: `List[Dict]`
- Description: List of conversation items in the session.

#### `run`

- Kind: `instance`
- Async: `true`
- Signature:

```python
def run(self, prompt: str, use_knowledge: Optional[bool] = None, collection_name: Optional[str] = None, session_id: str = None) -> AsyncIterator
```

**Summary**

Synchronously run a prompt using the agent inside an SQLite-backed session.

**Description**

Defaults to using an ephemeral in-memory SQLite database unless a persistent db_path is provided.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `prompt` | `str` | yes |  | Text prompt to run. |
| `use_knowledge` | `Optional[bool]` | no |  | Whether to utilize knowledge base augmentation. |
| `collection_name` | `Optional[str]` | no |  | Name of the knowledge collection to query. |
| `session_id` | `str` | no |  | Session ID, if not specified, a uuid-4 string will be applied. |

**Returns**

- Type: `agents.RunResult`
- Description: Result from agents.Runner.run execution (implementation-specific).

#### `run_streamed`

- Kind: `instance`
- Async: `true`
- Signature:

```python
def run_streamed(self, prompt: str, use_knowledge: Optional[bool] = None, collection_name: Optional[str] = None, session_id: str = None)
```

**Summary**

Run a prompt with the agent and process the output in a streaming fashion asynchronously.

**Description**

This method runs the asynchronous stream internally and processed the yield output from `stream`.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `prompt` | `str` | yes |  | Prompt text to run. |
| `use_knowledge` | `Optional[bool]` | no |  | Whether to augment prompt from knowledge base. |
| `collection_name` | `Optional[str]` | no |  | Name of the knowledge collection. |
| `session_id` | `str` | no |  | Session ID, if not specified, a uuid-4 string will be applied. |

**Returns**

- Type: `any`
- Description: AsyncIterator

#### `run_streamed_sync`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def run_streamed_sync(self, prompt: str, use_knowledge: Optional[bool] = None, collection_name: Optional[str] = None, session_id: str = None) -> agents.result.RunResult
```

**Summary**

Run a prompt with the agent and process the output in a streaming fashion synchronously.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `prompt` | `str` | yes |  | Prompt text to run. |
| `use_knowledge` | `Optional[bool]` | no |  | Whether to augment prompt from knowledge base. |
| `collection_name` | `Optional[str]` | no |  | Name of the knowledge collection. |
| `session_id` | `str` | no |  | Optional conversation session ID; generates new UUID if None. |

**Returns**

- Type: `RunResult`
- Description: agents.RunResult

#### `run_sync`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def run_sync(self, prompt: str, use_knowledge: Optional[bool] = None, collection_name: Optional[str] = None, session_id: str = None) -> agents.result.RunResult
```

**Summary**

Blocking call to run a prompt synchronously using the agent.

**Description**

Wraps agents.Runner.run_sync with an SQLite-backed session.

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `prompt` | `str` | yes |  | Prompt text to execute. |
| `use_knowledge` | `Optional[bool]` | no |  | Flag to enable prompt augmentation. |
| `collection_name` | `Optional[str]` | no |  | Knowledge collection name to use for augmentation. |
| `session_id` | `str` | no |  | Session ID, if not specified, a uuid-4 string will be applied. |

**Returns**

- Type: `agents.RunResult`
- Description: Result returned by agents.Runner.run_sync (implementation-specific).

#### `stream`

- Kind: `instance`
- Async: `false`
- Signature:

```python
def stream(self, prompt: str, use_knowledge: Optional[bool] = None, collection_name: Optional[str] = None, session_id: str = None) -> AsyncIterator
```

**Summary**

Asynchronously iterator to run a prompt and process streaming response events.

**Description**

Iterates over streamed events emitted by agents.Runner.run_streamed

**Parameters**

| Name | Type | Required | Default | Description |
| ---- | ---- | -------- | ------- | ----------- |
| `prompt` | `str` | yes |  | Prompt text to execute. |
| `use_knowledge` | `Optional[bool]` | no |  | Whether to augment prompt with knowledge base context. |
| `collection_name` | `Optional[str]` | no |  | Name of the knowledge collection to use. |
| `session_id` | `str` | no |  | Session ID, if not specified, a uuid-4 string will be applied. |

**Returns**

- Type: `AsyncIterator`
- Description: AsyncIterator
