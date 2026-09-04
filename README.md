# dccAIGen (DCC AI Generator & Pipeline Copilot)

基于现代 AI Agent 技术（LangGraph、MCP、Ollama、RAG、Pydantic）的游戏研发管线与 DCC（Houdini / Unreal Engine 5 / Maya）工具链自动化项目。

## 架构与核心规划
- 🎯 **强类型数据契约 (Pydantic)**：结构化参数校验，自然语言转 DCC 操作指令
- ⚡ **本地模型离线驱动 (Ollama)**：保护未公开游戏资产与私有代码安全
- 🔌 **DCC 工具标准化连接 (MCP)**：通过 Model Context Protocol 暴露 DCC 操作接口
- 🔄 **自愈式代码执行 (LangGraph)**：基于报错堆栈自动反思重试与修复

## 快速开始
```bash
# 激活环境
.\.venv\Scripts\activate

# 运行脚本
uv run python main.py
```
