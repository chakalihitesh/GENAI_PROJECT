from pathlib import Path
from dotenv import load_dotenv
from groq import Groq
import os
import time

# Ensure .env is loaded from project root or backend directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

load_dotenv(_PROJECT_ROOT / ".env")
if (_BACKEND_DIR / ".env").exists():
    load_dotenv(_BACKEND_DIR / ".env")


class LLMService:
    """
    Handles Groq generation for CodeLens AI.

    The model is instructed to answer only from repository
    evidence and to distinguish actual implementation/evidence
    from mentions of questions, tests, documentation, or examples.
    """

    PRIMARY_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")

    MAX_RETRIES_PER_MODEL = 2
    RETRY_DELAY_SECONDS = 1

    TEMPERATURE = 0.2

    FALLBACK_ANSWER = (
        "I couldn't find evidence of that "
        "in the uploaded repository."
    )

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            print(
                "WARNING: GROQ_API_KEY is not configured. Q&A answers will require GROQ_API_KEY in .env."
            )
            self.client = None
        else:
            self.client = Groq(
                api_key=api_key
            )

        self.models = [
            self.PRIMARY_MODEL,
            self.FALLBACK_MODEL,
            "llama-3.1-70b-versatile",
            "mixtral-8x7b-32768",
        ]

        print(
            "LLM service (Groq) initialized successfully."
        )

    # =========================================================
    # PROMPT BUILDER
    # =========================================================

    def build_prompt(
        self,
        question: str,
        context: str,
    ) -> str:
        """
        Build a strongly grounded repository-analysis prompt.
        """

        return f"""
You are CodeLens AI, an AI-powered software repository
understanding assistant.

Your job is to answer the user's question using ONLY
actual evidence contained in the provided repository context.

============================================================
CRITICAL GROUNDING RULES
============================================================

1. Answer using ONLY actual evidence contained in the provided repository context.

2. Do NOT invent files, functions, classes, APIs, technologies, dependencies, or behavior.

3. For project overview questions ("What is this project about?", "What does this codebase do?", "Explain this project"):
   - Synthesize the project's purpose from the provided README, file inventory, dependency manifests, and source code.
   - Provide a clear, structured summary of what the project does based strictly on the files.

4. For file inventory questions ("What files are in this repository?", "List the files"):
   - List the files shown in the provided repository context and file structure.

5. For technology / dependency questions ("What technologies or libraries are used?"):
   - List the languages, libraries, and frameworks found in the provided manifests (e.g. package.json, requirements.txt) and source code.

6. For code and implementation questions:
   - Provide direct answers citing actual file paths, classes, functions, and lines.
   - Distinguish between implementation, calling code, tests, and documentation.

7. If a specific feature is asked about and is ABSENT from the codebase (e.g. "How does authentication work?" or "Does it contain authentication?" when no auth code exists):
   - State clearly and directly that the feature is not implemented in this repository.
   - Mention which files were reviewed and that no matching logic was found.

8. If a question is completely unrelated to the software repository (e.g. "What is the capital of France?"):
   - Respond: "I couldn't find evidence of that in the uploaded repository."

============================================================
REPOSITORY CONTEXT
============================================================

{context}

============================================================
USER QUESTION
============================================================

{question}

============================================================
ANSWERING INSTRUCTIONS
============================================================

Answer the user's question clearly, thoroughly, and accurately using the repository context above according to the grounding rules.
"""

    # =========================================================
    # GROQ GENERATION
    # =========================================================

    def generate_answer(
        self,
        question: str,
        context: str,
    ) -> dict:
        """
        Generate a grounded answer using Groq.

        Returns:

        {
            "answer": "...",
            "model": "..."
        }
        """

        if not question or not question.strip():
            raise ValueError(
                "Question cannot be empty."
            )

        if not context or not context.strip():
            return {
                "answer": self.FALLBACK_ANSWER,
                "model": "Not used",
            }

        prompt = self.build_prompt(
            question=question,
            context=context,
        )

        if not self.client:
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.client = Groq(api_key=api_key)
            else:
                raise RuntimeError(
                    "GROQ_API_KEY is missing. Add it to the backend .env file."
                )

        last_error = None

        # -----------------------------------------------------
        # Try Groq models
        # -----------------------------------------------------

        for model_name in self.models:

            for attempt in range(
                self.MAX_RETRIES_PER_MODEL
            ):

                try:

                    print(
                        f"Trying Groq model: "
                        f"{model_name} "
                        f"(attempt "
                        f"{attempt + 1}/"
                        f"{self.MAX_RETRIES_PER_MODEL})"
                    )

                    response = self.client.chat.completions.create(
                        messages=[
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ],
                        model=model_name,
                        temperature=self.TEMPERATURE,
                    )

                    if not response or not response.choices:
                        raise RuntimeError(
                            "Groq returned an empty response."
                        )

                    choice = response.choices[0]
                    answer = getattr(
                        choice.message,
                        "content",
                        None,
                    )

                    if not answer or not answer.strip():
                        raise RuntimeError(
                            "Groq returned empty text."
                        )

                    answer = answer.strip()

                    print(
                        f"Groq generation successful "
                        f"using {model_name}"
                    )

                    return {
                        "answer": answer,
                        "model": model_name,
                    }

                except Exception as error:

                    last_error = error

                    err_msg = str(error)
                    print(
                        f"Groq model {model_name} "
                        f"failed: {error}"
                    )

                    if "invalid_api_key" in err_msg or "401" in err_msg:
                        raise RuntimeError(
                            "Invalid GROQ_API_KEY: please verify your Groq API key in .env"
                        ) from error

                    if (
                        attempt
                        < self.MAX_RETRIES_PER_MODEL - 1
                    ):
                        time.sleep(
                            self.RETRY_DELAY_SECONDS
                        )

            print(
                f"Trying fallback Groq model "
                f"after failure: {model_name}"
            )

        # -----------------------------------------------------
        # All models failed
        # -----------------------------------------------------

        raise RuntimeError(
            "All Groq models failed. "
            f"Last error: {last_error}"
        )
