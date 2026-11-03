from rag.search_service import SearchService
from rag.llm_service import LLMService
from config import REPOSITORIES_DIR
from services.repository_file_search import retrieve_file_search_chunks, list_files


class RAGService:
    """
    Retrieval-Augmented Generation service for CodeLens AI.

    Flow:

    User Question
          ↓
    Semantic Search + Additive File Search
          ↓
    Combined Repository Chunks & Locations
          ↓
    Context Builder
          ↓
    Groq LLM
          ↓
    Grounded Answer
          ↓
    Sources
    """

    # Maximum amount of repository context sent to LLM.
    MAX_CONTEXT_CHARACTERS = 24000

    def __init__(
        self,
        search_service: SearchService,
        llm_service: LLMService,
    ):
        self.search_service = search_service
        self.llm_service = llm_service

    # =========================================================
    # SOURCE LABEL
    # =========================================================

    def build_source_label(
        self,
        metadata: dict,
    ) -> str:
        """
        Create a human-readable source label.
        """
        file_path = metadata.get(
            "file_path",
            "Unknown file",
        )
        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")
        name = metadata.get("name")

        if start_line is not None and end_line is not None:
            line_info = f"Lines {start_line}-{end_line}"
        elif start_line is not None:
            line_info = f"Line {start_line}"
        else:
            line_info = "Line information unavailable"

        if name:
            return f"{file_path} | {name} | {line_info}"
        return f"{file_path} | {line_info}"

    # =========================================================
    # CONTEXT BUILDER
    # =========================================================

    def build_context(
        self,
        search_results: list[dict],
    ) -> str:
        """
        Convert retrieved repository chunks into structured context for LLM.
        """
        if not search_results:
            return ""

        context_parts = []
        total_characters = 0

        for index, result in enumerate(
            search_results,
            start=1,
        ):
            metadata = result.get(
                "metadata",
                {},
            )
            content = result.get(
                "content",
                "",
            )
            if not content:
                continue

            file_path = metadata.get(
                "file_path",
                "Unknown file",
            )
            name = metadata.get(
                "name",
                "",
            )
            start_line = metadata.get(
                "start_line",
                "?",
            )
            end_line = metadata.get(
                "end_line",
                "?",
            )
            chunk_type = metadata.get(
                "chunk_type",
                "unknown",
            )

            source_block = (
                f"SOURCE {index}\n"
                f"File: {file_path}\n"
                f"Name: {name or 'N/A'}\n"
                f"Lines: {start_line}-{end_line}\n"
                f"Chunk type: {chunk_type}\n"
                f"\n"
                f"Repository content:\n"
                f"{content}\n"
                f"\n"
                f"{'=' * 60}\n"
            )

            block_length = len(source_block)

            if total_characters + block_length > self.MAX_CONTEXT_CHARACTERS:
                remaining = self.MAX_CONTEXT_CHARACTERS - total_characters
                if remaining < 500:
                    break

                truncated_block = (
                    source_block[:remaining]
                    + "\n[Context truncated]"
                )
                context_parts.append(truncated_block)
                total_characters += len(truncated_block)
                break

            context_parts.append(source_block)
            total_characters += block_length

        return "\n".join(context_parts)

    # =========================================================
    # SOURCE BUILDER
    # =========================================================

    def build_sources(
        self,
        search_results: list[dict],
    ) -> list[dict]:
        """
        Convert search metadata into clean source references.
        """
        sources = []
        seen_sources = set()

        for result in search_results:
            metadata = result.get(
                "metadata",
                {},
            )
            file_path = metadata.get(
                "file_path",
                "Unknown file",
            )
            start_line = metadata.get("start_line")
            end_line = metadata.get("end_line")
            chunk_type = metadata.get("chunk_type")
            name = metadata.get("name")
            distance = result.get("distance")

            source_key = (
                file_path,
                start_line,
                end_line,
                name,
            )

            if source_key in seen_sources:
                continue

            seen_sources.add(source_key)

            sources.append({
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "chunk_type": chunk_type,
                "name": name,
                "distance": distance,
            })

        return sources

    # =========================================================
    # ANSWER QUESTION
    # =========================================================

    def answer_question(
        self,
        repository_id: str,
        question: str,
        top_k: int = 5,
    ) -> dict:
        """
        Complete RAG pipeline with additive file search.

        1. Retrieve relevant repository chunks (semantic vector search)
        2. Perform additive file inventory & literal code-location search
        3. Build structured context from combined evidence
        4. Send context + question to LLM
        5. Return answer + sources + retrieved chunks
        """
        if not repository_id:
            raise ValueError("repository_id is required.")

        if not question or not question.strip():
            raise ValueError("Question cannot be empty.")

        if top_k <= 0:
            raise ValueError("top_k must be greater than 0.")

        # -----------------------------------------------------
        # STEP 1: RETRIEVE (SEMANTIC + ADDITIVE FILE SEARCH)
        # -----------------------------------------------------

        search_results = (
            self.search_service.search(
                repository_id=repository_id,
                query=question,
                top_k=top_k,
            )
        )

        repo_root = REPOSITORIES_DIR / repository_id
        file_chunks = []
        if repo_root.is_dir():
            try:
                file_chunks = retrieve_file_search_chunks(repo_root, question)
            except Exception as e:
                print(f"Additive file search retrieval error: {e}")
                file_chunks = []

            # Check if query is about project overview, files, or technologies, or if search results are sparse
            q_lower = question.lower()
            is_broad_query = any(k in q_lower for k in [
                "project about", "what is this", "what does", "overview", "architecture",
                "what files", "which files", "list files", "file list", "structure",
                "technolog", "librar", "dependenc", "framework", "package", "stack", "contains", "contain"
            ])

            if is_broad_query or not search_results:
                try:
                    from repository.manager import summarize_languages, parse_dependency_manifests
                    lang_summary = summarize_languages(repo_root)
                    manifests = parse_dependency_manifests(repo_root)
                    all_files = list_files(repo_root)

                    overview_lines = [
                        f"Repository Total Files: {lang_summary.get('source_file_count', len(all_files))}",
                        "Detected Languages: " + ", ".join(f"{l['name']} ({l['file_count']} files)" for l in lang_summary.get("languages", [])),
                    ]
                    if manifests:
                        for m in manifests[:3]:
                            deps = [f"{d['name']} ({d['version']})" for d in m.get("dependencies", [])[:15]]
                            overview_lines.append(f"Manifest '{m['file']}': " + ", ".join(deps))

                    file_sample = [f["path"] for f in all_files[:40]]
                    overview_lines.append("Repository File List:\n" + "\n".join(f"- {p}" for p in file_sample))

                    file_chunks.insert(0, {
                        "content": "REPOSITORY OVERVIEW & FILE INVENTORY:\n" + "\n".join(overview_lines),
                        "metadata": {
                            "file_path": "Repository Overview",
                            "name": "repository_overview",
                            "start_line": 1,
                            "end_line": len(overview_lines),
                            "chunk_type": "repository_overview",
                        },
                        "distance": 0.0,
                    })
                except Exception as meta_err:
                    print(f"Repository metadata enrichment error: {meta_err}")

        all_results = file_chunks + (search_results or [])

        # -----------------------------------------------------
        # STEP 2: NO RESULTS
        # -----------------------------------------------------

        if not all_results:
            return {
                "answer": (
                    "I couldn't find evidence of that "
                    "in the uploaded repository."
                ),
                "sources": [],
                "retrieved_chunks": [],
                "model": "Not used",
            }

        # -----------------------------------------------------
        # STEP 3: BUILD CONTEXT
        # -----------------------------------------------------

        context = self.build_context(all_results)

        # -----------------------------------------------------
        # STEP 4: SAFETY CHECK
        # -----------------------------------------------------

        if not context.strip():
            return {
                "answer": (
                    "I couldn't find evidence of that "
                    "in the uploaded repository."
                ),
                "sources": [],
                "retrieved_chunks": all_results,
                "model": "Not used",
            }

        # -----------------------------------------------------
        # STEP 5: GENERATE ANSWER
        # -----------------------------------------------------

        generation_result = (
            self.llm_service.generate_answer(
                question=question,
                context=context,
            )
        )

        # -----------------------------------------------------
        # STEP 6: BUILD SOURCES
        # -----------------------------------------------------

        sources = self.build_sources(all_results)

        # -----------------------------------------------------
        # STEP 7: FINAL RESPONSE
        # -----------------------------------------------------

        return {
            "answer": generation_result["answer"],
            "sources": sources,
            "retrieved_chunks": all_results,
            "model": generation_result["model"],
        }
