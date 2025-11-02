import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Callable,
    Tuple,
    AsyncIterator,
    TYPE_CHECKING,
)


import dotenv
import agents
import litellm
from openai.types.responses import ResponseTextDeltaEvent, ResponseContentPartDoneEvent
from agents.extensions.models.litellm_model import LitellmModel

from .util import setup_logger

if TYPE_CHECKING:
    import chromadb


class _ChromaVectorStore:

    def __init__(
        self, client: "chromadb.PersistentClient", name: str, embed_fn: Callable
    ):
        """Initialize an internal Chroma-backed vector store wrapper.

        Args:
            client (chromadb.PersistentClient): Chroma persistent client instance used to create/get collections.
            name (str): Name of the Chroma collection to manage.
            embed_fn (Callable): Callable that takes a list of strings and returns list of embeddings.
        """
        self.collection = client.get_or_create_collection(name=name)
        self.embed_fn = embed_fn

    def __len__(self):
        """Return the number of items stored in the underlying Chroma collection.

        Returns:
            int: Number of documents in the collection. Returns 0 if the count cannot be retrieved.
        """
        try:
            return self.collection.count()
        except Exception:
            return 0

    def add_texts(self, texts, metadatas=None):
        """Add a list of text documents with optional metadata into the collection.

        The function will generate stable ids for documents based on metadata 'source'
        and 'chunk_index' if provided, compute embeddings via the embed_fn, and upsert
        documents into the Chroma collection.

        Args:
            texts (Iterable[str]): Iterable of text chunks to insert.
            metadatas (Optional[Iterable[dict]]): Iterable of metadata dicts corresponding to each text.
                If not provided, empty metadata dicts will be used.

        Returns:
            int: Number of texts added.
        """
        if metadatas is None:
            metadatas = [{} for _ in texts]
        ids = []
        for i, m in enumerate(metadatas):
            src = m.get("source", "unknown")
            idx = m.get("chunk_index", i)
            ids.append(f"{src}::chunk::{idx}")
        vecs = self.embed_fn(texts)
        self.collection.upsert(
            documents=texts, embeddings=vecs, metadatas=metadatas, ids=ids
        )
        return len(texts)

    def search(self, query, k=5):
        """Search the collection for documents most similar to the query.

        Embeds the query with embed_fn, performs a Chroma nearest-neighbor query and
        converts Chroma distances into heuristic similarity scores (1.0 - distance).

        Args:
            query (str): Query string to search for.
            k (int): Number of top results to return.

        Returns:
            List[Tuple[str, dict, float]]: A list of tuples (document_text, metadata, score).
        """
        q_emb = self.embed_fn([query])[0]
        res = self.collection.query(query_embeddings=[q_emb], n_results=k)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        results = []
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - float(dist)
            results.append((doc, meta, score))
        return results


class Collection:
    """Manage an LLM agent knowledge store backed by a persistent Chroma vector database and OpenAI-compatible embeddings.

    This class provides convenience methods to ingest text files, split them into chunks, compute embeddings,
    store and retrieve vectors from a persistent Chroma instance, and optionally apply an LLM-based reranker.
    It centralizes configuration for embedding and reranking models, vector DB path, chunking behavior, and logging.

    Attributes:
        default_collection (str): Default collection name used when none is provided to load/search methods.
        embedding_model (Optional[str]): Name of the embedding model used to compute embeddings.
        chunk_size (int): Maximum number of characters per chunk when splitting documents.
        chunk_overlap (int): Number of characters overlapping between adjacent chunks.
        retrieval_top_k (int): Default number of top vector search results to return.
        reranker_model (Optional[str]): Optional model name for LLM-based reranking. When None, reranking is disabled.
        rerank_top_k (int): Number of documents to keep after reranking (or used as reranker top_n).
        _vector_db_path (str): Filesystem path where the Chroma persistent database is stored.
        _chroma (chromadb.PersistentClient): Underlying persistent Chroma client instance.
        collections (Dict[str, _ChromaVectorStore]): In-memory map of collection name to _ChromaVectorStore wrappers.
        _rerank_fn (Optional[Callable]): Internal callable performing reranking when configured.
        logger: Logger instance used for informational and error messages.

    Example:
        >>> col = Collection(default_collection="notes", embedding_model="text-embedding-3-small", vector_db_path=".kb")
        >>> col.load_knowledge("/path/to/docs")
        >>> results = col.search_knowledge("How to configure the system?")
    """

    def __init__(
        self,
        default_collection: str = "default",
        base_url: str = None,
        api_key: str = None,
        embedding_model: str = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        retrieval_top_k: int = 5,
        vector_db_path: str = None,
        reranker_model: Optional[str] = None,
        rerank_top_k: Optional[int] = None,
        log_level: str = "INFO",
        log_file: Union[str, Path] = None,
    ):
        """Initialize a Collection used as an LLM agent knowledge store backed by Chroma and OpenAI embeddings.

        This constructor sets up the OpenAI client, embedding model, persistent Chroma client,
        local collections map, optional LLM reranker, and logging.

        Args:
            default_collection (str): Default collection name to use for loading and searching knowledge.
            base_url (Optional[str]): Base URL for the OpenAI-compatible API. If None, read from LITELLM_BASE_URL env.
            api_key (Optional[str]): API key for the OpenAI-compatible API. If None, read from LITELLM_API_KEY env.
            embedding_model (Optional[str]): Embedding model name. If None, read from LITELLM_EMBEDDING_MODEL env.
            chunk_size (int): Maximum number of characters per text chunk.
            chunk_overlap (int): Overlap size in characters between adjacent chunks.
            retrieval_top_k (int): Number of top vector search results to return by default.
            vector_db_path (Optional[str]): Filesystem path to persist Chroma DB. If None, read from AGENT_VECTOR_DB_PATH env or default '.knowledge'.
            reranker_model (Optional[str]): Optional reranker model name used for LLM-based re-ranking.
            rerank_top_k (Optional[int]): Number of documents to keep after reranking. If None, uses retrieval_top_k.
            log_level (str): Logging level name.
            log_file (Optional[Union[str, Path]]): Optional path to a log file.

        """
        dotenv.load_dotenv()
        try:
            import chromadb
        except:
            raise ImportError(
                'Chroma backend not found, please install with `pip install "parquool[knowledge]"`'
            )
        self.base_url = (
            base_url or os.getenv("LITELLM_BASE_URL") or "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.getenv("LITELLM_API_KEY")
        self.embedding_model = embedding_model or os.getenv("LITELLM_EMBEDDING_MODEL")
        self.default_collection = default_collection
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.retrieval_top_k = retrieval_top_k
        self._vector_db_path = (
            vector_db_path or os.getenv("AGENT_VECTOR_DB_PATH") or ".knowledge"
        )
        self.logger = setup_logger(
            f"Collection({self._vector_db_path})", file=log_file, level=log_level
        )
        self._chroma = chromadb.PersistentClient(path=self._vector_db_path)
        self.collections: Dict[str, Agent._MemoryVectorStore] = {}
        self._hydrate_persistent_collections()
        self._rerank_fn = None
        self.reranker_model = reranker_model or os.getenv("LITELLM_RERANKER_MODEL")
        self.rerank_top_k = rerank_top_k or retrieval_top_k
        self._setup_reranker()

    # ----------------- Vector database / Embeddings basic tools -----------------

    def _hydrate_persistent_collections(self):
        """Load existing Chroma collections from the persistent path into the in-memory collections map.

        The method queries the Chroma client for collections and wraps each into _ChromaVectorStore
        using the configured embedding function. Failures are logged and swallowed.
        """
        try:
            existing = self._chroma.list_collections()
            for coll in existing:
                name = getattr(coll, "name", None)
                if not name:
                    continue
                self.collections[name] = _ChromaVectorStore(
                    client=self._chroma,
                    name=name,
                    embed_fn=self._embed_texts,
                )
            self.logger.info(
                f"Hydrated {len(self.collections)} collections from '{self._vector_db_path}'."
            )
        except Exception as e:
            self.logger.warning(f"Failed to hydrate Chroma collections: {e}")

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Compute embeddings for a list of texts using the configured OpenAI-compatible embedding client.

        Args:
            texts (List[str]): List of input strings to embed.

        Returns:
            List[List[float]]: List of embedding vectors corresponding to each input.

        Raises:
            Exception: Re-raises any underlying embedding error after logging.
        """
        if not texts:
            return []
        try:
            resp = litellm.embedding(
                model=self.embedding_model,
                input=texts,
                api_base=self.base_url,
                api_key=self.api_key,
            )
            return [d["embedding"] for d in resp.data]
        except Exception as e:
            self.logger.error(f"Embedding failed: {e}")
            raise

    def _get_or_create_collection(self, collection_name: str):
        """Get an existing in-memory collection wrapper or create a new one backed by Chroma.

        Args:
            collection_name (str): Name of the collection to fetch or create.

        Returns:
            _ChromaVectorStore: Wrapper instance for the requested collection.
        """
        store = self.collections.get(collection_name)
        if store:
            return store
        store = _ChromaVectorStore(
            client=self._chroma,
            name=collection_name,
            embed_fn=self._embed_texts,
        )
        self.collections[collection_name] = store
        return store

    def _split_text(self, text: str) -> List[str]:
        """Split a long text into chunks according to configured chunk_size and chunk_overlap.

        Chunks are created by sliding a fixed-size window with configured overlap. Empty or whitespace-only
        chunks are ignored.

        Args:
            text (str): Input text to split.

        Returns:
            List[str]: List of non-empty text chunks.
        """
        text = text.strip()
        if not text:
            return []
        chunks = []
        n = len(text)
        step = max(1, self.chunk_size - self.chunk_overlap)
        for start in range(0, n, step):
            end = min(n, start + self.chunk_size)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= n:
                break
        return chunks

    def _read_file_text(self, path: Path) -> str:
        """Read textual content from a file path for supported file types.

        Supported plain-text-like suffixes are read directly. For PDF and DOCX, optional libraries
        (pypdf and python-docx) are used where available. Unsupported binary files are skipped.

        Args:
            path (Path): Filesystem path to read.

        Returns:
            str: Extracted text. Empty string if reading fails or file type is unsupported.
        """
        suffix = path.suffix.lower()
        # Pure text
        text_like = {
            ".txt",
            ".md",
            ".rst",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".tsv",
            ".xml",
            ".html",
            ".htm",
            ".ini",
            ".cfg",
            ".toml",
            ".log",
        }
        if suffix in text_like:
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                self.logger.warning(f"Failed to read {path}: {e}")
                return ""

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                pages = [p.extract_text() or "" for p in reader.pages]
                return "\n".join(pages)
            except Exception as e:
                self.logger.warning(f"To read PDF install pypdf. Skip {path}: {e}")
                return ""

        if suffix == ".docx":
            try:
                import docx  # python-docx

                doc = docx.Document(str(path))
                return "\n".join([p.text for p in doc.paragraphs])
            except Exception as e:
                self.logger.warning(
                    f"To read DOCX install python-docx. Skip {path}: {e}"
                )
                return ""

        self.logger.info(f"Skip non-text file: {path}")
        return ""

    def _setup_reranker(self):
        """Configure an optional LLM-based reranking function if a reranker model is provided.

        The configured rerank function will call litellm.rerank with the configured model and
        normalize the returned results into a list of {"index": int, "score": float} items.
        If no reranker_model is set, the method is a no-op.
        """
        if not self.reranker_model:
            self.logger.debug("No reranker model configured; skip reranking.")
            return

        def _llm_rerank(
            query: str, docs: List[str], metas: List[Dict], top_n: Optional[int] = None
        ):
            if not docs:
                return []
            top_n = min(top_n or len(docs), len(docs))

            data = litellm.rerank(
                model=self.reranker_model,
                query=query,
                documents=docs,
                top_n=top_n,
                return_documents=False,
                api_base=self.base_url,
                api_key=self.api_key,
            )

            items = None
            if isinstance(data, dict):
                items = data.get("results")
            if not isinstance(items, list):
                items = data if isinstance(data, list) else []

            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                idx = it.get("index")
                if idx is None:
                    continue
                score = it.get("relevance_score")
                try:
                    idx = int(idx)
                except Exception:
                    continue
                try:
                    score = float(score) if score is not None else None
                except Exception:
                    score = None
                if 0 <= idx < len(docs):
                    out.append({"index": idx, "score": score})

            if out and all(o.get("score") is not None for o in out):
                out.sort(key=lambda x: x["score"], reverse=True)
            return out[:top_n]

        self._rerank_fn = _llm_rerank
        self.logger.info(f"LLM reranker enabled (model={self.reranker_model}).")

    def _normalize_rerank_result(
        self, res: List, n_docs: int
    ) -> List[Tuple[int, Optional[float]]]:
        """Normalize various reranker result formats into a list of (index, score) tuples.

        Accepts integer indices, (index, score) tuples/lists, or dicts with 'index' and optional 'score'.
        Filters out invalid indices and sorts by score descending if all items have scores.

        Args:
            res (List): Raw reranker output in one of several accepted formats.
            n_docs (int): Number of documents that were reranked (used to validate indices).

        Returns:
            List[Tuple[int, Optional[float]]]: Normalized and optionally sorted list of (index, score).
        """
        ranked: List[Tuple[int, Optional[float]]] = []
        if not isinstance(res, list) or not res:
            return ranked
        for item in res:
            idx = None
            score = None
            if isinstance(item, int):
                idx = item
            elif isinstance(item, (tuple, list)) and len(item) >= 1:
                idx = int(item[0])
                if len(item) > 1:
                    try:
                        score = float(item[1])
                    except Exception:
                        score = None
            elif isinstance(item, dict):
                if "index" in item:
                    idx = int(item["index"])
                if item.get("score") is not None:
                    try:
                        score = float(item["score"])
                    except Exception:
                        score = None
            if idx is not None and 0 <= idx < n_docs:
                ranked.append((idx, score))
        if ranked and all(s is not None for _, s in ranked):
            ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def load(
        self,
        path_or_paths: Union[str, Path, List[Union[str, Path]]],
        collection_name: Optional[str] = None,
        recursive: bool = True,
        include_globs: Optional[List[str]] = None,
        exclude_globs: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Load files from one or more paths into the specified collection as vectorized knowledge chunks.

        The method discovers files according to include/exclude glob patterns, reads text from supported files,
        splits texts into chunks, computes embeddings and upserts them to the target collection. It returns
        counts of files and chunks added.

        Args:
            path_or_paths (Union[str, Path, List[Union[str, Path]]]): Single path or list of paths (files or directories).
            collection_name (Optional[str]): Target collection name. Defaults to the instance default_collection.
            recursive (bool): Whether to search directories recursively when applying include_globs.
            include_globs (Optional[List[str]]): List of glob patterns to include. If None, a sensible default list is used.
            exclude_globs (Optional[List[str]]): List of glob patterns to exclude from the discovered files.

        Returns:
            Dict[str, int]: Summary dictionary with keys 'files' and 'chunks' indicating how many files and chunks were loaded.
        """
        collection_name = collection_name or self.default_collection
        store = self._get_or_create_collection(collection_name)

        if isinstance(path_or_paths, (str, Path)):
            paths = [path_or_paths]
        else:
            paths = list(path_or_paths)

        include_globs = include_globs or [
            "**/*.md",
            "**/*.txt",
            "**/*.py",
            "**/*.json",
            "**/*.yaml",
            "**/*.yml",
            "**/*.csv",
            "**/*.tsv",
            "**/*.html",
            "**/*.htm",
            "**/*.log",
            "**/*.rst",
        ]
        exclude_globs = exclude_globs or []

        files: List[Path] = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                for pattern in include_globs:
                    for fp in (
                        p.glob(pattern)
                        if recursive
                        else p.glob(pattern.replace("**/", ""))
                    ):
                        files.append(fp)
            elif p.is_file():
                files.append(p)
            else:
                self.logger.warning(f"Path not found or unsupported: {p}")

        exclude_set = set()
        for pat in exclude_globs:
            for f in list(files):
                if f.match(pat):
                    exclude_set.add(f)
        files = [f for f in files if f not in exclude_set]

        files = sorted(set(files))
        file_count = 0
        chunk_count = 0
        for f in files:
            text = self._read_file_text(f)
            if not text.strip():
                continue
            chunks = self._split_text(text)
            if not chunks:
                continue
            metadatas = [
                {"source": str(f), "chunk_index": i} for i in range(len(chunks))
            ]
            added = store.add_texts(chunks, metadatas)
            if added > 0:
                file_count += 1
                chunk_count += added

        self.logger.info(
            f"Knowledge loaded into collection '{collection_name}': files={file_count}, chunks={chunk_count}"
        )
        return {"files": file_count, "chunks": chunk_count}

    def search(
        self,
        query: str,
        collection_name: Optional[str] = None,
    ) -> List[Dict]:
        """Search the knowledge store for documents relevant to the query, optionally reranking with an LLM.

        Performs vector search in the specified collection and, if configured, reranks top candidates using
        the LLM reranker. Results include text, metadata, vector score, and optional rerank_score.

        Args:
            query (str): Query string to search for.
            collection_name (Optional[str]): Collection name to search. Defaults to the instance default_collection.

        Returns:
            List[Dict]: List of result dictionaries. Each dictionary contains keys:
                - 'text' (str): The document text/chunk.
                - 'metadata' (dict): Associated metadata for the chunk.
                - 'score' (float): Similarity score from the vector store (heuristic).

                - 'rerank_score' (Optional[float]): Optional reranker relevance score when reranking is enabled.
        """
        collection_name = collection_name or self.default_collection
        store = self.collections.get(collection_name)
        if not store or len(store) == 0:
            self.logger.info(f"No knowledge found in collection '{collection_name}'.")
            return []
        hits = store.search(
            query, k=self.retrieval_top_k
        )  # [(text, meta, sim_score), ...]

        if not self._rerank_fn:
            return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]

        try:
            docs = [t for t, _, _ in hits]
            metas = [m for _, m, _ in hits]
            top_n = min(len(docs), self.rerank_top_k or len(docs))

            raw = self._rerank_fn(query, docs, metas, top_n=top_n)
            ranked = self._normalize_rerank_result(raw, n_docs=len(docs))
            if not ranked:
                self.logger.debug(
                    "Reranker returned empty/invalid result; fallback to vector order."
                )
                return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]

            used = set()
            reranked_results: List[Dict] = []
            for idx, rscore in ranked:
                t, m, s = hits[idx]
                reranked_results.append(
                    {"text": t, "metadata": m, "score": s, "rerank_score": rscore}
                )
                used.add(idx)

            for i, (t, m, s) in enumerate(hits):
                if len(reranked_results) >= self.rerank_top_k:
                    break
                if i not in used:
                    reranked_results.append({"text": t, "metadata": m, "score": s})

            return reranked_results[: self.retrieval_top_k]
        except Exception as e:
            self.logger.warning(f"Reranking failed: {e}. Fallback to vector order.")
            return [{"text": t, "metadata": m, "score": s} for t, m, s in hits]


class Agent:
    """
    High-level wrapper that simplifies construction and interaction with an LLM-based agent.

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

    Attributes:
        logger (logging.Logger): Logger configured for this wrapper.
        agent (agents.Agent): Underlying agent instance that performs reasoning, tool calls, and messaging.
        model (LitellmModel): Model client used by the underlying agent.
        model_settings (agents.ModelSettings): Model settings forwarded to the agent.
        tools (dict): Mapping of tool name to callable for convenience tools.
        function_tools (List[agents.Tool]): List of agents-compatible function tools registered on the agent.
        handoff_agents (List[agents.Agent]): List of agents to which the wrapper can hand off control.
        preset_prompts (dict): Optional preset prompts for common tasks.
        collection (Collection | None): Optional knowledge collection used for RAG augmentation.
        rag_prompt_template (str): Template used to format augmented prompts with retrieved context.
        rag_max_context (int): Maximum total length of concatenated context used for RAG.

    Example:
        >>> agent = Agent(model_name="gpt-4", log_level="DEBUG", collection=my_collection)
        >>> result = agent.run("Summarize the conversation.")
    """

    def __init__(
        self,
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
        handoffs: List[agents.Agent] = None,
        output_type: str = None,
        input_guardrails: List[agents.InputGuardrail] = None,
        output_guardrails: List[agents.OutputGuardrail] = None,
        default_openai_api: str = "chat_completions",
        trace_disabled: bool = True,
        collection: Collection = None,
        rag_max_context: int = 6000,
        rag_prompt_template: str = None,
        session_id: str = None,
        session_db: Union[Path, str] = ":memory:",
    ):
        """
        Initialize the Agent wrapper, configure OpenAI client, tracing, logging, and set up the underlying agent.

        This initializer:
        - Loads environment variables.
        - Configures OpenAI client based on inputs or environment variables.
        - Enables or disables tracing.
        - Sets up logging based on given log level and file.
        - Creates the internal agents.Agent instance with provided settings.

        Args:
            base_url (str, optional): Base URL for the OpenAI client. Defaults to environment variable LITELLM_BASE_URL if not set.
            api_key (str, optional): API key for the OpenAI client. Defaults to environment variable LITELLM_API_KEY if not set.
            name (str): Name of the agent wrapper and underlying agent.
            log_file (str, optional): Path to file for logging output.
            log_level (str): Logging verbosity level (e.g. "INFO", "DEBUG").
            model_name (str, optional): Name of the model to use. Defaults to environment variable LITELLM_MODEL_NAME if not set.
            model_settings (dict, optional): Additional model configuration forwarded to agents.ModelSettings.
            instructions (str): High-level instructions for the underlying agent.
            preset_prompts (dict, optional): Dictionary of preset prompts for common tasks.
            tools (List[agents.FunctionTool], optional): List of tool descriptors or callables to add to the agent.
            tool_use_behavior (str): Strategy for how tools are used by the agent.
            handoffs (List[agents.Agent], optional): List of handoff agents.
            output_type (str, optional): Optional output type annotation for the agent.
            input_guardrails (List[agents.InputGuardrail], optional): List of input guardrails to enforce.
            output_guardrails (List[agents.OutputGuardrail], optional): List of output guardrails to enforce.
            default_openai_api (str): Default OpenAI API endpoint to use (e.g. "chat_completions").
            trace_disabled (bool): If True, disables tracing features.
            collection (Collection, optional): Knowledge collection for retrieval-augmented generation (RAG).
            rag_max_context (int): Maximum total context length for RAG augmentation.
            rag_prompt_template (str, optional): Template string for prompt augmentation with retrieved context.
            session_id (str, optional): Session ID, if not specified, a uuid-4 string will be applied.
            session_db (str, optional): Path to session database file (sqlite), if not specified, in-memory database will be used.

        Returns:
            None
        """
        dotenv.load_dotenv()
        agents.set_default_openai_api(api=default_openai_api)
        agents.set_tracing_disabled(disabled=trace_disabled)
        self.logger = setup_logger(name, file=log_file, level=log_level)

        self.handoff_agents = []
        for handoff in handoffs or []:
            if isinstance(handoff, Agent):
                self.handoff_agents.append(handoff.agent)
            elif isinstance(handoff, agents.Agent):
                self.handoff_agents.append(handoff)
            else:
                self.logger.warning(
                    "handoffs must be BaseAgent or agents.Agent instances"
                )

        self.function_tools = []
        self.tools = {}
        for fnt in tools or []:
            if isinstance(fnt, agents.Tool):
                self.function_tools.append(fnt)
            elif callable(fnt):
                self.tools[fnt.__name__] = fnt
                self.function_tools.append(agents.function_tool(fnt))
            else:
                self.logger.warning("tools must be agents.Tool or callable instances")

        self.model = LitellmModel(
            base_url=base_url
            or os.getenv("LITELLM_BASE_URL")
            or "https://api.openai.com/v1",
            api_key=api_key or os.getenv("LITELLM_API_KEY"),
            model=model_name or os.getenv("LITELLM_MODEL_NAME"),
        )

        model_settings = model_settings or dict()
        if isinstance(model_settings, dict):
            model_settings.update({"include_usage": True})
            self.model_settings = agents.ModelSettings(**model_settings)
        elif isinstance(model_settings, agents.ModelSettings):
            self.model_settings = model_settings
        elif not isinstance(model_settings, agents.ModelSettings):
            self.logger.warning(
                "model_settings must be a dict or agents.ModelSettings instance"
            )

        self.collection = collection
        if not isinstance(self.collection, Collection) and not self.collection is None:
            self.collection = None
            self.logger.warning("collections must be Collection instances")
        self.rag_max_context = rag_max_context

        self.agent = agents.Agent(
            name=name,
            instructions=instructions,
            output_type=output_type,
            tools=self.function_tools,
            tool_use_behavior=tool_use_behavior,
            handoffs=self.handoff_agents,
            model=self.model,
            model_settings=self.model_settings,
            input_guardrails=input_guardrails or list(),
            output_guardrails=output_guardrails or list(),
        )
        self.preset_prompts = preset_prompts or dict()
        self.rag_prompt_template = rag_prompt_template or (
            "You are a helpful assistant. Use the following context to answer the question. "
            "If the context is not sufficient, say you don't know.\n\n"
            "Context:\n{context}\n\n"
            "Question:\n{question}"
        )

        self.session_id = session_id or uuid.uuid4().hex
        self.session_db = session_db
        self.session = agents.SQLiteSession(
            session_id=self.session_id, db_path=self.session_db
        )

    # ----------------- Internal helpers -----------------

    def __str__(self):
        return str(self.agent)

    def __repr__(self):
        return self.__str__()

    # ----------------- Internal helpers -----------------

    def _build_context_from_hits(self, hits: List[Dict]) -> str:
        """
        Build a concatenated context string from a list of knowledge base search hits.

        This limits the total length of the accumulated context to self.rag_max_context.

        Args:
            hits (List[Dict]): List of knowledge search result documents.

        Returns:
            str: Concatenated context string constructed from the hits.
        """
        if not hits:
            return ""
        parts = []
        total = 0
        for h in hits:
            src = h.get("metadata", {}).get("source", "unknown")
            snippet = h["text"].strip().replace("\n", " ").strip()
            piece = f"[source: {src}]\n{snippet}\n"
            if total + len(piece) > self.rag_max_context:
                break
            parts.append(piece)
            total += len(piece)
        return "\n".join(parts)

    def _maybe_augment_prompt(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = False,
        collection_name: Optional[str] = "default",
    ) -> str:
        """
        Conditionally augment the prompt input using retrieval from the knowledge collection.

        If knowledge usage is enabled and a collection is present, the prompt is augmented with
        relevant context retrieved from the collection, formatted according to the RAG template.

        Args:
            prompt (str): Original prompt text.
            use_knowledge (Optional[bool]): Whether to augment prompt using the knowledge base.
            collection_name (Optional[str]): Name of the collection to query in the knowledge base.

        Returns:
            str: Augmented prompt if applicable, otherwise original prompt.
        """
        if self.collection is None or not use_knowledge:
            return prompt

        collection_name = collection_name or self.collection.default_collection

        try:
            hits = self.collection.search(prompt, collection_name=collection_name)
            if not hits:
                return prompt
            context = self._build_context_from_hits(hits)
            if not context.strip():
                return prompt
            aug = self.rag_prompt_template.format(context=context, question=prompt)
            return aug
        except Exception as e:
            self.logger.warning(
                f"RAG augmentation failed, fallback to original prompt. Err: {e}"
            )
            return prompt

    # ----------------- Public interfaces -----------------

    def as_tool(self, tool_name: str, tool_description: str):
        """
        Expose this agent as a tool descriptor compatible with agents.Tool.

        This acts as a wrapper around the underlying agent's as_tool method.

        Args:
            tool_name (str): Name to expose for the tool.
            tool_description (str): Description of the tool's functionality.

        Returns:
            agents.Tool: A Tool descriptor instance for integration with other agents.
        """
        return self.agent.as_tool(
            tool_name=tool_name, tool_description=tool_description
        )

    def export_conversation(self, output_file: str, limit: int = None):
        """
        Export an SQLite session's conversation history to a JSON file.

        Args:
            output_file (str): Path to the JSON file to save the exported conversation.
            limit (int): Limit number of conversation

        Returns:
            None
        """
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(
                self.get_conversation(limit),
                f,
                indent=2,
            )

    def get_conversation(self, limit: int = None):
        """
        Retrieve the conversation history for a given SQLite session.

        Args:
            limit (int): Limit number of conversation

        Returns:
            List[Dict]: List of conversation items in the session.
        """
        return asyncio.run(self.session.get_items(limit))

    async def stream(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ) -> AsyncIterator:
        """
        Asynchronously iterator to run a prompt and process streaming response events.

        Iterates over streamed events emitted by agents.Runner.run_streamed

        Args:
            prompt (str): Prompt text to execute.
            use_knowledge (Optional[bool], optional): Whether to augment prompt with knowledge base context.
            collection_name (Optional[str], optional): Name of the knowledge collection to use.

        Returns:
            None
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )

        result = agents.Runner.run_streamed(
            self.agent,
            prompt_to_run,
            session=self.session,
        )
        async for event in result.stream_events():
            yield event

    # ----------------- Running triggers -----------------

    async def run(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Synchronously run a prompt using the agent inside an SQLite-backed session.

        Defaults to using an ephemeral in-memory SQLite database unless a persistent db_path is provided.

        Args:
            prompt (str): Text prompt to run.
            use_knowledge (Optional[bool], optional): Whether to utilize knowledge base augmentation.
            collection_name (Optional[str], optional): Name of the knowledge collection to query.

        Returns:
            Any: Result from agents.Runner.run execution (implementation-specific).
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        return agents.Runner.run(
            self.agent,
            prompt_to_run,
            session=self.session,
        )

    def run_sync(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Blocking call to run a prompt synchronously using the agent.

        Wraps agents.Runner.run_sync with an SQLite-backed session.

        Args:
            prompt (str): Prompt text to execute.
            use_knowledge (Optional[bool], optional): Flag to enable prompt augmentation.
            collection_name (Optional[str], optional): Knowledge collection name to use for augmentation.

        Returns:
            Any: Result returned by agents.Runner.run_sync (implementation-specific).
        """
        use_knowledge = True if self.collection else False
        prompt_to_run = self._maybe_augment_prompt(
            prompt=prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        return agents.Runner.run_sync(
            self.agent,
            prompt_to_run,
            session=self.session,
        )

    async def run_streamed(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Run a prompt with the agent and process the output in a streaming fashion asynchronously.

        This method runs the asynchronous stream internally and processed the yield output from `stream`.

        Args:
            prompt (str): Prompt text to run.
            session_id (str, optional): Optional conversation session ID; generates new UUID if None.
            db_path (str, optional): Path to SQLite DB file; defaults to ":memory:".
            use_knowledge (Optional[bool], optional): Whether to augment prompt from knowledge base.
            collection_name (Optional[str], optional): Name of the knowledge collection.

        Returns:
            None
        """

        events = self.stream(
            prompt,
            use_knowledge=use_knowledge,
            collection_name=collection_name,
        )
        async for event in events:
            # We'll print streaming delta if available
            if event.type == "raw_response_event" and isinstance(
                event.data, ResponseTextDeltaEvent
            ):
                print(event.data.delta, end="", flush=True)
            elif event.type == "raw_response_event" and isinstance(
                event.data, ResponseContentPartDoneEvent
            ):
                print()
            elif event.type == "agent_updated_stream_event":
                self.logger.debug(f"Agent updated: {event.new_agent.name}")
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    self.logger.info(
                        f"<TOOL_CALL> {event.item.raw_item.name}(arguments: {event.item.raw_item.arguments})"
                    )
                elif event.item.type == "tool_call_output_item":
                    self.logger.info(f"<TOOL_OUTPUT> {event.item.output}")
                elif event.item.type == "message_output_item":
                    self.logger.info(
                        f"<MESSAGE> {agents.ItemHelpers.text_message_output(event.item)}"
                    )
                else:
                    pass

    def run_streamed_sync(
        self,
        prompt: str,
        use_knowledge: Optional[bool] = None,
        collection_name: Optional[str] = None,
    ):
        """
        Run a prompt with the agent and process the output in a streaming fashion synchronously.

        Args:
            prompt (str): Prompt text to run.
            session_id (str, optional): Optional conversation session ID; generates new UUID if None.
            db_path (str, optional): Path to SQLite DB file; defaults to ":memory:".
            use_knowledge (Optional[bool], optional): Whether to augment prompt from knowledge base.
            collection_name (Optional[str], optional): Name of the knowledge collection.

        Returns:
            None
        """
        asyncio.run(
            self.run_streamed(
                prompt=prompt,
                use_knowledge=use_knowledge,
                collection_name=collection_name,
            )
        )
