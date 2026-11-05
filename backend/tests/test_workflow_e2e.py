import sys
from pathlib import Path
import pytest

# Ensure utf-8 stdout on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from main import app
from services.progress_service import progress_service
from config import REPOSITORIES_DIR, METADATA_DIR

client = TestClient(app)

TEST_REPO_URL = "https://github.com/chakalihitesh/Green_Plant_Selling.git"


def test_complete_e2e_workflow():
    """
    Test complete CodeLens AI workflow with https://github.com/chakalihitesh/Green_Plant_Selling.git:
    1. GitHub Import / Clone & Folder unnesting
    2. File inventory & Lockfile filtering
    3. Indexing & Progress polling
    4. On-disk persistence across simulated server reboot
    5. All 5 test questions with Groq Q&A
    6. Missing repository handling
    """
    print("\n--- STEP 1: GitHub Import ---")
    import_resp = client.post("/api/repositories/github", json={"url": TEST_REPO_URL})
    assert import_resp.status_code == 200, import_resp.text
    import_data = import_resp.json()
    repo_id = import_data["repository_id"]
    repo_info = import_data["repository"]

    assert repo_id is not None
    assert repo_info["file_count"] > 0
    print(f"Repository imported: ID={repo_id}, Files={repo_info['file_count']}")

    # Verify no lockfile or .git in indexed files
    indexed_files = repo_info["files"]
    assert not any("package-lock.json" in f for f in indexed_files)
    assert not any(".git" in f for f in indexed_files)
    # Verify unnesting: files are relative to repo root, like 'src/App.tsx'
    normalized_paths = [f.replace("\\", "/") for f in indexed_files]
    assert any("src/App.tsx" in p for p in normalized_paths)
    assert any("src/index.css" in p for p in normalized_paths)
    assert any("package.json" in p for p in normalized_paths)

    print("\n--- STEP 2: Progress before indexing ---")
    p0 = client.get(f"/api/repositories/{repo_id}/progress")
    assert p0.status_code == 200
    p0_data = p0.json()
    assert p0_data["status"] in {"ready_for_indexing", "uploaded", "pending"}
    assert p0_data["repository_id"] == repo_id

    print("\n--- STEP 3: Indexing ---")
    index_resp = client.post(f"/api/repositories/{repo_id}/index?sync=true")
    assert index_resp.status_code == 200, index_resp.text
    index_data = index_resp.json()
    assert index_data["status"] == "completed"
    assert index_data["total_chunks"] > 0
    print(f"Indexing completed: {index_data['total_chunks']} chunks from {index_data['total_files']} files.")

    print("\n--- STEP 4: Progress polling after indexing ---")
    p_done = client.get(f"/api/repositories/{repo_id}/progress")
    assert p_done.status_code == 200
    p_data = p_done.json()
    assert p_data["status"] == "completed"
    assert p_data["progress"] == 100

    print("\n--- STEP 5: Persistence across simulated restart ---")
    # Verify metadata JSON exists on disk
    meta_path = METADATA_DIR / f"{repo_id}.json"
    assert meta_path.is_file(), f"Metadata file {meta_path} should exist on disk"
    repo_meta_path = REPOSITORIES_DIR / repo_id / ".codelens_meta.json"
    assert repo_meta_path.is_file(), f"Repository metadata file {repo_meta_path} should exist"

    # Simulate restart by wiping in-memory dictionary
    progress_service._progress.clear()
    assert repo_id not in progress_service._progress

    # Progress endpoint should reload from disk without error
    p_reloaded = client.get(f"/api/repositories/{repo_id}/progress")
    assert p_reloaded.status_code == 200
    assert p_reloaded.json()["status"] == "completed"
    print("Persistence verified: successfully recovered state from disk.")

    print("\n--- STEP 6: Testing the 5 User Questions via /ask ---")
    questions = [
        ("How many CSS files are in this repository?", ["1", "one", "index.css"]),
        ("Where is the authentication logic implemented?", ["App.tsx", "server", "index.js", "AuthScreen", "OTP"]),
        ("How does the application connect to the database?", ["database", "mock", "localStorage", "no database", "in-memory", "otpStorage"]),
        ("Explain the project folder structure.", ["src", "server", "App.tsx", "index.js", "Vite", "React"]),
        ("Which file handles email authentication?", ["server/index.js", "index.js", "App.tsx", "nodemailer", "send-otp"]),
    ]

    for q_idx, (question, expected_keywords) in enumerate(questions, start=1):
        print(f"\nAsking Question {q_idx}: {question}")
        ask_resp = client.post(
            f"/api/repositories/{repo_id}/ask",
            json={"question": question, "top_k": 5}
        )
        assert ask_resp.status_code == 200, ask_resp.text
        ans_data = ask_resp.json()
        assert "answer" in ans_data
        assert "sources" in ans_data
        assert len(ans_data["answer"].strip()) > 20
        answer_text = ans_data["answer"].lower()
        print(f"Answer {q_idx}: {ans_data['answer'][:150]}...")
        # Check that answer contains relevant information
        found_any = any(kw.lower() in answer_text for kw in expected_keywords)
        assert found_any, f"Expected at least one of {expected_keywords} in answer: {ans_data['answer']}"
        print(f"Sources returned: {len(ans_data['sources'])}")

    print("\n--- STEP 7: Missing Repository Handling ---")
    missing_id = "nonexistent_repo_999"
    missing_ask = client.post(
        f"/api/repositories/{missing_id}/ask",
        json={"question": "What is this?", "top_k": 5}
    )
    assert missing_ask.status_code == 404
    assert "not found on server" in missing_ask.json()["detail"].lower()

    missing_prog = client.get(f"/api/repositories/{missing_id}/progress")
    assert missing_prog.status_code == 404
    assert "does not exist on server" in missing_prog.json()["detail"].lower()
    print("Missing repository correctly returned 404 with actionable detail.")

    print("\nALL WORKFLOW TESTS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    test_complete_e2e_workflow()
