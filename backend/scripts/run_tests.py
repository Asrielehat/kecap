"""Run offline tests in an isolated directory; never read project keys or user data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

backend = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="kecap-tests-") as folder:
    env = {**os.environ, "PYTHONPATH": str(backend), "SQLITE_PATH": f"{folder}/test.db",
           "QDRANT_PATH": f"{folder}/qdrant", "QDRANT_URL": "", "UPLOAD_DIR": f"{folder}/uploads",
           "DATABASE_URL_OVERRIDE": "", "LLM_API_KEY": "offline-test", "EMBEDDING_API_KEY": "offline-test",
           "EMBEDDING_DIM": "4", "DEBUG": "false", "MCP_ENABLED": "false", "SKILLS_ENABLED": "false",
           "AGENT_PLANNING_ENABLED": "false", "AGENT_RETRIEVAL_ENABLED": "false", "ANSWER_SELFCHECK_ENABLED": "false", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(backend / "tests"), "-v"],
                            cwd=folder, env=env)
    sys.exit(result.returncode)
