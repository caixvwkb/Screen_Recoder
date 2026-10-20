# workstation — 本地 AI 工作站（ScreenRecoder 子模块）

在 ScreenRecoder 项目内实现本地 AI 工作站：vLLM 独立进程推理（DeepSeek-7B-AWQ），
**OCR / ASR 直接复用本项目现有引擎**（同项目 import，不跨项目、不重复开发）。

## 架构

- `core/model_client.py`：OpenAI 兼容 SSE 流式对话（分流 reasoning_content）
- `core/vllm_manager.py`：vLLM 进程管理（启停/端口轮询/退出清理进程树）
- `core/searcher.py`：研究库 SQLite FTS5 检索（秒级筛文件喂模型）
- `core/session.py`：会话/配置持久化
- `capabilities/`：能力抽象（Capability 基类）
  - `ocr.py`：识图 → 复用项目根 OCR 引擎（rapidocr_onnxruntime）
  - `asr.py`：语音转写 → 复用项目根 `asr.py`（SenseVoice，--asr-worker 子进程模式）
  - `terminal.py`：本机命令执行（受限白名单）
  - `search.py`：库检索（供模型调用的工具）
  - `file_io.py`：文件读写/拼接 prompt/输出保存

## 环境与模型

```powershell
# vLLM（独立 venv，避免污染本项目系统 Python）
python -m venv D:\Projects\QT_Projects\screen_recoder\.venv_ai
D:\Projects\QT_Projects\screen_recoder\.venv_ai\Scriptsctivate
pip install vllm

# 模型（约 5GB，国内超时用 HF_ENDPOINT=https://hf-mirror.com）
huggingface-cli download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B-AWQ --local-dir D:\Projects\QT_Projects\screen_recoder\models\llm\DeepSeek-R1-Distill-Qwen-7B-AWQ
```

## 启动 vLLM 验证

```powershell
python -m vllm.entrypoints.openai.api_server --model models\llm\DeepSeek-R1-Distill-Qwen-7B-AWQ --quantization awq --gpu-memory-utilization 0.9 --port 8000
```
