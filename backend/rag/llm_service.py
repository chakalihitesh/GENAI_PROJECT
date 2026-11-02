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

    PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")

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

1. Do NOT use outside knowledge.

2. Do NOT invent files, functions, classes, APIs,
   technologies, dependencies, behavior, or facts.

3. Repository context may contain:
   - source code
   - documentation
   - README files
   - test files
   - evaluation questions
   - examples
   - comments
   - configuration files

   These are not automatically evidence for the answer.

4. A question appearing inside a README, test file,
   evaluation list, example, comment, or documentation
   does NOT mean that the repository contains the answer
   to that question.

5. If the context only shows that the user's question is
   mentioned, tested, listed, or used as an example, but
   does NOT provide the actual answer, you MUST NOT answer
   the question using general knowledge.

6. For example, if the context contains:

   "The evaluation includes:
    What is the capital of France?"

   this is NOT evidence that the repository knows the
   capital of France.

   In that situation, respond exactly:

   "I couldn't find evidence of that in the uploaded repository."

7. Only answer a factual question when the repository
   context contains actual evidence supporting that answer.

8. For code questions, actual source code is strong evidence.

9. For implementation questions, distinguish between:
   - code that implements functionality
   - code that calls functionality
   - code that tests functionality
   - documentation describing functionality

10. If multiple files provide actual evidence, combine them
    and explain their relationship.

11. If the evidence is insufficient, incomplete, or only
    indirectly related to the question, use the fallback
    response instead of guessing.

12. Never answer from general knowledge simply because you
    recognize the question.

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

First determine whether the repository context contains
actual evidence that can answer the question.

If YES:
- provide a clear answer
- mention relevant files
- mention functions/classes when applicable
- mention line ranges when available
- explain relationships between files when useful

If NO:
respond exactly:

"I couldn't find evidence of that in the uploaded repository."

Do not add outside knowledge to the fallback case.
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
