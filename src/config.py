"""Pinned experiment settings. Changing these invalidates earlier runs."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TSVC_SRC = ROOT / "third_party" / "TSVC_2" / "src"

# Compiler (mirrors TSVC_2's Makefile.clang: -O3 -fstrict-aliasing, native arch)
CC = os.environ.get("CC_BIN", "clang")
CFLAGS = ["-O3", "-fstrict-aliasing", "-march=native"]
REMARK_FLAGS = [
    "-Rpass=loop-vectorize",
    "-Rpass-missed=loop-vectorize",
    "-Rpass-analysis=loop-vectorize",
]

# LLM. Model is an open decision: set LLM_MODEL in .env or change the default.
MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
TEMPERATURE = 0.8
MAX_TOKENS = 4096
TRIALS = 5

# Local alternative (src.llm_local); no API key or Anthropic SDK is needed.
LOCAL_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LOCAL_CONTEXT_TOKENS = int(os.environ.get("OLLAMA_NUM_CTX", "4096"))
LOCAL_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "600"))

RESULTS_CSV = ROOT / "results" / "results.csv"
RAW_DIR = ROOT / "results" / "raw"
CLANG_REMARKS_DIR = ROOT / "remarks" / "clang"
