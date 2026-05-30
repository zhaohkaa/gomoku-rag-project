# AI-Powered Gomoku with RAG-enhanced QA & Review
**基于 LLM + RAG 的可解释 AI 五子棋对战与智能分析系统**
IEMS5709 Group13 Final Project

---

## 项目背景
传统五子棋 AI 系统大多仅专注于棋力与胜负，缺乏可解释性、教学能力和深度分析能力。玩家在对弈过程中无法理解 AI 决策逻辑、无法获得实时指导、难以通过复盘提升水平。
大语言模型（LLM）虽具备强大的理解与生成能力，但在垂直领域易出现回答不准确、依据不足、专业性不强等问题。
本项目结合 **LLM + RAG 检索增强技术**，构建一套可解释、可交互、可教学的智能五子棋系统，使 AI 从单纯的对弈工具升级为具备分析、讲解、复盘、指导能力的智能教练。

---

## 项目目标
- 实现完整的五子棋人机对弈功能
- 提供实时棋局问答与 AI 走子可解释性
- 基于 RAG 提升回答的准确性、专业性与可溯源性
- 自动生成棋局复盘、胜率分析与关键转折点识别
- 支持复盘报告导出
- 根据对弈行为生成棋风人格画像

---

## 核心功能
### 1. 人机对战
- 15×15 标准五子棋棋盘
- 玩家执黑先行，AI 自动应对
- AI 采用 LLM 智能走子 + 启发式算法兜底
- 实时胜负判定与规则校验

### 2. 实时棋局 QA（RAG 增强）
- 规则解释：活三、冲四、双三等
- 局面分析：优劣势判断、攻防建议
- AI 决策解释：为什么 AI 这样下
- Top3 最佳落子推荐与棋盘高亮展示

### 3. 智能复盘系统
- 自动提取关键转折点、失误步、威胁点
- 生成胜率变化曲线
- 分析棋局节奏、攻防转换与决策问题
- 提供针对性改进建议

### 4. 复盘报告导出
- 一键下载 Markdown 格式复盘报告
- 包含棋局总结、关键步、错误分析、优化建议

### 5. 棋风人格测评
- 自动判断棋风类型：激进进攻 / 稳健防守 / 均衡型
- 分析优势、潜在风险与提升方向
- 生成完整棋风人格画像

---

## 技术栈
- 前端：React + TypeScript + Tailwind CSS
- 后端：FastAPI (Python 3.10+)
- AI 引擎：Qwen3 / DeepSeek + vLLM
- RAG：FAISS / Chroma 向量库
- 数据库：PostgreSQL
- 部署：Docker + GitHub Actions

---

## 系统架构
1. **前端层**：Web UI、棋盘交互、QA 面板、复盘面板
2. **后端服务层**：FastAPI 网关、游戏引擎、AI 走子、历史记录
3. **AI/LLM 层**：问答生成、复盘分析、人格画像、RAG 检索
4. **知识层**：规则库、战术库、开局库、向量检索
5. **基础设施**：容器化、监控、CI/CD

---

## 主要模块
- Gomoku Game Engine：棋盘状态、落子校验、胜负判定
- AI Move Engine：LLM 走子 + 启发式兜底
- History Recorder：走子历史与棋局状态记录
- Move QA Module：意图识别 + RAG 检索 + 回答生成
- Review Analyzer：复盘、胜率、转折点、失误分析
- Report Exporter：复盘报告导出
- Personality Profiler：棋风分类与画像生成
- RAG Retriever：规则/战术/开局知识库检索

---

## 快速启动
```bash
git clone https://github.com/zhaohkaa/gomoku-rag-project.git
cd gomoku-rag-project/Project/Gomoku
pip install -r requirements.txt
uvicorn app.app:app --host 0.0.0.0 --port 9898
访问地址：http://localhost:9898



