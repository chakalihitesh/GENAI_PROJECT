import gc
import os
import threading

# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Number of documents embedded in one batch.
# Kept to 16 by default to stay within Render 512MB RAM constraints.
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "8"))


class EmbeddingService:
    """
    Create embeddings for CodeLens AI code chunks.

    Optimized for memory-constrained environments (e.g. Render 512 MB RAM):
    - Loads the all-MiniLM-L6-v2 model on-demand (lazy loading), not at startup.
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
    # LAZY MODEL INITIALIZATION
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
        Uses torch.inference_mode() to avoid building graph memory.
        """

        if not documents:
            return []

        import torch

        all_embeddings = []
        total_documents = len(documents)

        # ----------------------------------------------------
        # Process documents batch-by-batch
        # ----------------------------------------------------
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
