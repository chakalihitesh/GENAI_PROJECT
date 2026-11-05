import gc
import os
import threading

# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Number of documents embedded in one batch.
# Kept to 8 by default to stay within Render 512MB RAM constraints.
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "8"))


class EmbeddingService:
    """
    Create embeddings for CodeLens AI code chunks.

    Optimized for memory-constrained environments (e.g. Render 512 MB RAM):
    - Prioritizes Gemini Cloud Embeddings (text-embedding-004) when GEMINI_API_KEY is present
      (0 MB server RAM consumption, eliminates Render OOM crashes).
    - Falls back cleanly to sentence-transformers/all-MiniLM-L6-v2 on-demand (lazy loaded).
    - Forces single-threaded PyTorch execution to eliminate thread pool memory overhead.
    - Uses torch.inference_mode() to prevent autograd graph allocations.
    - Processes documents in small batches and explicitly triggers garbage collection.
    """

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        if batch_size <= 0:
            raise ValueError(
                "Embedding batch size must be greater than 0."
            )

        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    # ========================================================
    # GEMINI CLOUD EMBEDDINGS (ZERO SERVER RAM OVERHEAD)
    # ========================================================

    def _embed_gemini(self, documents: list[str]) -> list[list[float]]:
        """
        Embed documents via Google Gemini text-embedding-004 REST API.
        Uses 0 MB server memory and avoids PyTorch/SentenceTransformers overhead on Render.
        """
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key={gemini_key}"
        all_embeddings = []
        batch_size = 20

        for i in range(0, len(documents), batch_size):
            chunk_batch = documents[i : i + batch_size]
            requests_payload = [
                {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": str(doc)[:8000]}]}
                }
                for doc in chunk_batch
            ]

            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, json={"requests": requests_payload})
                if res.status_code != 200:
                    raise RuntimeError(f"Gemini embedding API returned HTTP {res.status_code}: {res.text}")
                data = res.json()
                for item in data.get("embeddings", []):
                    all_embeddings.append(item.get("values", []))

        return all_embeddings

    # ========================================================
    # LAZY MODEL INITIALIZATION (LOCAL SENTENCETRANSFORMER)
    # ========================================================

    @property
    def model(self):
        """
        Returns the SentenceTransformer model instance.
        Loads the model on-demand upon first call, keeping initial
        application memory footprint low (~60MB on startup).
        """
        if self._model is None:
            with self._lock:
                if self._model is None:
                    print(
                        f"Lazy loading embedding model on demand: {self.model_name}"
                    )
                    import torch
                    from sentence_transformers import SentenceTransformer

                    try:
                        torch.set_num_threads(1)
                    except Exception:
                        pass

                    try:
                        loaded = SentenceTransformer(self.model_name, local_files_only=True)
                    except Exception:
                        loaded = SentenceTransformer(self.model_name)
                    if hasattr(loaded, "eval"):
                        loaded.eval()

                    self._model = loaded
                    print("Embedding model loaded successfully on demand.")

        return self._model

    def is_loaded(self) -> bool:
        """Check whether the model is currently resident in memory."""
        return self._model is not None

    def unload_model(self) -> None:
        """
        Explicitly free the embedding model from memory to reclaim RAM
        when the application is idle.
        """
        with self._lock:
            if self._model is not None:
                del self._model
                self._model = None
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                print("Embedding model unloaded from memory.")

    # ========================================================
    # DOCUMENT EMBEDDINGS
    # ========================================================

    def embed_documents(
        self,
        documents: list[str]
    ) -> list[list[float]]:
        """
        Create embeddings for multiple documents in small batches.
        Uses Gemini API if available (0 MB RAM), otherwise PyTorch inference.
        """
        if not documents:
            return []

        # Step 1: Attempt ultra-lightweight Gemini API if key is available
        if os.getenv("GEMINI_API_KEY"):
            try:
                return self._embed_gemini(documents)
            except Exception as gemini_err:
                print(f"Gemini cloud embedding failed: {gemini_err}. Falling back to local SentenceTransformer...")

        # Step 2: Fall back to local SentenceTransformer
        import torch

        all_embeddings = []
        total_documents = len(documents)

        with torch.inference_mode():
            for start in range(0, total_documents, self.batch_size):
                end = min(start + self.batch_size, total_documents)
                batch = documents[start:end]

                embeddings = self.model.encode(
                    batch,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=min(len(batch), self.batch_size),
                )

                all_embeddings.extend(embeddings.tolist())

                del batch
                del embeddings

        # Clean up memory after batch processing
        gc.collect()

        return all_embeddings

    # ========================================================
    # QUERY EMBEDDING
    # ========================================================

    def embed_query(
        self,
        query: str
    ) -> list[float]:
        """
        Create an embedding for a user query.
        """
        if not query or not query.strip():
            raise ValueError(
                "Query cannot be empty."
            )

        # Step 1: Attempt ultra-lightweight Gemini API if key is available
        if os.getenv("GEMINI_API_KEY"):
            try:
                results = self._embed_gemini([query])
                if results and len(results) > 0:
                    return results[0]
            except Exception as gemini_err:
                print(f"Gemini cloud query embedding failed: {gemini_err}. Falling back to local model...")

        # Step 2: Fall back to local SentenceTransformer
        import torch

        with torch.inference_mode():
            embedding = self.model.encode(
                query,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            result = embedding.tolist()
            del embedding

        return result
