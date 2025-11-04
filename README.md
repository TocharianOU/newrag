# SmartResume - Intelligent Resume Parsing System

<div align="center">
  <img src="assets/logo.png" alt="SmartResume Logo" width="80%" >
</div>

<p align="center">
    🤗 <a href="https://www.modelscope.cn/models/Alibaba-EI/SmartResume">Model</a>&nbsp&nbsp | &nbsp&nbsp📑 <a href="https://arxiv.org/abs/2510.09722">Technical Report</a>
</p>

<p align="right"><b>English</b> | <a href="README_CN.md">中文</a></p>


## Project Introduction
SmartResume is an layout‑aware resume parsing system. It ingests resumes in PDF, image and common Office formats, extracts clean text (OCR + PDF metadata), reconstructs reading order with layout detection, and leverages LLMs to convert content into structured fields such as basic info, education, and work experience.

[demo](https://github.com/user-attachments/assets/5814b880-cdb5-41d8-9534-cf6e6909c136)

## Quick Start

### Requirements

- Python >= 3.9
- CUDA >= 11.0 (optional, for GPU acceleration)
- Memory >= 8GB
- Storage >= 10GB

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/alibaba/SmartResume.git
cd SmartResume
```

2. **Create conda environment**
```bash
conda create -n resume_parsing python=3.9
conda activate resume_parsing
```

3. **Install dependencies**
```bash
pip install -e .
```

4. **Configure environment**
```bash
# Copy configuration template
cp configs/config.yaml.example configs/config.yaml
# Edit configuration file and add API keys
vim configs/config.yaml
```

### Basic Usage

#### Method 1: Command Line Interface (Recommended)

```bash
# Parse single resume file
python scripts/start.py --file resume.pdf

# Specify extraction types
python scripts/start.py --file resume.pdf --extract_types basic_info work_experience education
```

#### Method 2: Python API

```python
from smartresume import ResumeAnalyzer

# Initialize analyzer
analyzer = ResumeAnalyzer(init_ocr=True, init_llm=True)

# Parse resume
result = analyzer.pipeline(
    cv_path="resume.pdf",
    resume_id="resume_001",
    extract_types=["basic_info", "work_experience", "education"]
)

print(result)
```

### Local Model Deployment

SmartResume now supports local model deployment using vLLM, reducing dependency on external APIs:

```bash
# Download Qwen-0.6B-resume model
python scripts/download_models.py

# Deploy model
bash scripts/start_vllm.sh
```

For detailed local model deployment guide, see [LOCAL_MODELS.md](docs/LOCAL_MODELS.md).


## Key Features

| Metric Category | Specific Metric | Value | Description |
|----------------|----------------|-------|-------------|
| **Layout Detection** | mAP@0.5 | **92.1%** | High layout detection accuracy |
| **Information Extraction** | Overall Accuracy | **93.1%** | High accuracy |
| **Processing Speed** | Single Page Time | **1.22s** | High performance |
| **Language Support** | Supported Languages | **many** | Covering major global languages |


### Benchmark Results

For detailed benchmark results, see [Benchmark Results](docs/BENCHMARK_RESULTS_EN.md).

## Configuration

For detailed configuration options, see the [Configuration Guide](docs/CONFIGURATION.md).

### Quick Configuration

Copy the configuration template and edit as needed:

```bash
cp configs/config.yaml.example configs/config.yaml
```

Key configuration areas:
- **Model Settings**: API keys, model selection, and parameters
- **Processing Options**: OCR settings and output formats
- **Local Models**: vLLM deployment and GPU configuration

## License Information

This project is licensed under the [LICENSE.md](LICENSE.md).

Currently, some models in this project were previously trained with third-party detectors. We plan to explore and replace them with models under more permissive licenses to enhance user-friendliness and flexibility.

## Acknowledgments

- [PDFplumber](https://github.com/jsvine/pdfplumber)
- [EasyOCR](https://github.com/JaidedAI/EasyOCR)

## Citation
```bibtex
@article{Zhu2025SmartResume,
  title={Layout-Aware Parsing Meets Efficient LLMs: A Unified, Scalable Framework for Resume Information Extraction and Evaluation},
  author={Fanwei Zhu and Jinke Yu and Zulong Chen and Ying Zhou and Junhao Ji and Zhibo Yang and Yuxue Zhang and Haoyuan Hu and Zhenghao Liu},
  journal={arXiv preprint arXiv:2510.09722},
  year={2025},
  url={https://arxiv.org/abs/2510.09722}
}
```

---

**Note**: Please ensure compliance with relevant laws and regulations and privacy policies.
