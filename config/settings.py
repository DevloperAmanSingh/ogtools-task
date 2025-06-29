#!/usr/bin/env python3

import os

TEAM_ID = "aline123"
OUTPUT_DIR = "outputs"
JINA_READER_BASE = "https://r.jina.ai/"

GEMINI_CONFIG = {
    "model": "gemini-1.5-flash",
    "temperature": 0,
    "max_output_tokens": 2000
}

PRICING = {
    "input": 0.00035,
    "output": 0.00053
}

CHUNKING = {
    "max_chunk_size": 20000,
    "overlap": 1000
}

def get_api_key():
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") 