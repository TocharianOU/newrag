#!/bin/bash
cd "$(dirname "$0")/.."
source .venv/bin/activate
python document_ocr_pipeline/process_document.py "$@"

