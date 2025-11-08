# SmartResume - 智能简历解析系统

<div align="center">
  <img src="assets/logo.png" alt="SmartResume Logo" width="80%" >
</div>

<p align="center">
    💻 <a href="https://github.com/alibaba/SmartResume">Code</a>&nbsp&nbsp | &nbsp&nbsp🤗 <a href="https://www.modelscope.cn/models/Alibaba-EI/SmartResume">Model</a>&nbsp&nbsp | &nbsp&nbsp🤖 <a href="https://modelscope.cn/studios/Alibaba-EI/SmartResumeDemo/summary">Demo</a>&nbsp&nbsp | &nbsp&nbsp📑 <a href="https://arxiv.org/abs/2510.09722">Technical Report</a>
</p>

<p align="right"><a href="README.md">English</a> | <b>中文</b></p>


## 项目介绍
SmartResume 是一个面向版面结构的智能简历解析系统，系统支持 PDF、图片及常见 Office 文档格式，融合 OCR 与 PDF 元数据完成文本提取，结合版面检测重建阅读顺序，并通过 LLM 将内容转换为结构化字段（如：基本信息、教育经历、工作经历等）。系统同时支持远程 API 和本地模型部署，提供灵活的使用方式。

[demo](https://github.com/user-attachments/assets/5814b880-cdb5-41d8-9534-cf6e6909c136)


## 快速开始

### 环境要求

- Python >= 3.9
- CUDA >= 11.0 (可选，用于GPU加速)
- 内存 >= 8GB
- 存储 >= 10GB

#### 本地模型部署额外要求

- GPU: 推荐 NVIDIA GPU，6GB+ VRAM（用于本地模型推理）
- 内存: 推荐 16GB+（本地模型需要更多内存）
- 存储: 每个模型需要 2-10GB 存储空间

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/alibaba/SmartResume.git
cd SmartResume
```

2. **创建conda环境**
```bash
conda create -n resume_parsing python=3.9
conda activate resume_parsing
```

3. **安装依赖**
```bash
pip install -e .
```

4. **配置环境**
```bash
# 复制配置文件模板
cp configs/config.yaml.example configs/config.yaml
# 编辑配置文件，添加API密钥
vim configs/config.yaml
```


### 基本使用

#### 方法1: 使用命令行界面（推荐）

```bash
# 解析单个简历文件
python scripts/start.py --file resume.pdf

# 指定提取类型
python scripts/start.py --file resume.pdf --extract_types basic_info work_experience education
```

#### 方法2: 使用Python API

```python
from smartresume import ResumeAnalyzer

# 初始化分析器
analyzer = ResumeAnalyzer(init_ocr=True, init_llm=True)

# 解析简历
result = analyzer.pipeline(
    cv_path="resume.pdf",
    resume_id="resume_001",
    extract_types=["basic_info", "work_experience", "education"]
)

print(result)
```

### 本地模型部署

SmartResume 现在支持使用 vLLM 进行本地模型部署，减少对外部 API 的依赖：

```bash
# 下载 Qwen-0.6B-resume 模型
python scripts/download_models.py

# 部署模型
bash scripts/start_vllm.sh
```

详细的本地模型部署指南请参考 [LOCAL_MODELS](docs/LOCAL_MODELS.md)。


## 核心特色

| 指标类别 | 具体指标 | 数值 | 说明 |
|---------|---------|------|------|
| **布局检测** | mAP@0.5 | **92.1%** | 高布局检测精度 |
| **信息抽取** | 整体准确率 | **93.1%** | 高准确率 |
| **处理速度** | 单页处理时间 | **1.22s** | 高性能 |
| **多语言支持** | 支持语言数 | **多种** | 覆盖全球主要语言 |

### 基准结果

详细的基准测试结果请参考 [基准测试结果](docs/BENCHMARK_RESULTS.md)。

## 配置说明

详细的配置选项请参考 [配置指南](docs/CONFIGURATION.md)。

### 快速配置

复制配置模板并根据需要编辑：

```bash
cp configs/config.yaml.example configs/config.yaml
```

主要配置区域：
- **模型设置**: API密钥、模型选择和参数配置
- **处理选项**: OCR设置和输出格式
- **本地模型**: vLLM部署和GPU配置

## License Information

本项目采用 [LICENSE](LICENSE)。

未来我们将逐步替换为更宽松许可的方案，以提升用户友好度与灵活性。

## 重要说明

受限于开源合规性问题，代码是重构版本，内部PDF解析和OCR无法公布，使用的开源版本平替，部分功能未全部兼容。

## TODO List

1. **避免每次加载模型、兼容vllm部署后调用** - 优化模型加载机制，避免重复加载，并兼容vLLM部署后的调用方式
2. **水印和损坏PDF解析走OCR链路** - 对于有水印或损坏的PDF文件，使用OCR链路进行解析
3. **更简单的调用方式** - 简化API调用方式，提升易用性

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


**注意**: 请确保项目使用遵守相关法律法规和隐私政策。

