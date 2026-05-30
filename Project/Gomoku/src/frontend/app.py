import copy
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import BOARD_SIZE, BLACK, EMPTY, WHITE, GomokuGame
from history import HistoryRecorder
from llm_client import LLMClient
from rag.retriever import RAGRetriever
from report_exporter import ReportExporter
from review_analyzer import ReviewAnalyzer


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
RAG_DIR = BASE_DIR / "rag"
KNOWLEDGE_PATH = RAG_DIR / "knowledge.json"

# 默认不让每一步 AI 落子都等待 LLM，避免页面一落子就长时间 loading。
# 如果你确实想让 LLM 控制 AI 落子，启动前设置：export USE_LLM_FOR_AI_MOVE=true
USE_LLM_FOR_AI_MOVE = os.getenv("USE_LLM_FOR_AI_MOVE", "false").lower() in {"1", "true", "yes", "y"}

app = FastAPI(title="Gomoku Current Session API")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class CurrentSessionStore:
    game: GomokuGame
    history: HistoryRecorder
    last_review_result: Optional[dict] = None

    def reset(self) -> None:
        self.game = GomokuGame()
        self.history = HistoryRecorder()
        self.last_review_result = None


current_session = CurrentSessionStore(
    game=GomokuGame(),
    history=HistoryRecorder(),
)

retriever = RAGRetriever(KNOWLEDGE_PATH)
review_analyzer = ReviewAnalyzer()
report_exporter = ReportExporter()

_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
        try:
            _llm_client.connect()
        except Exception:
            pass
    return _llm_client


# -----------------------------
# Pydantic Models
# -----------------------------
class HealthResponse(BaseModel):
    status: str


class NewGameResponse(BaseModel):
    board: list[list[int]]
    current_player: str
    game_over: bool


class PlayTurnRequest(BaseModel):
    x: int
    y: int


class PlayTurnResponse(BaseModel):
    board: list[list[int]]
    human_move: dict
    ai_move: Optional[dict] = None
    reasoning: Optional[str] = None
    winner: Optional[str] = None
    game_over: bool


class WhyRequest(BaseModel):
    step_id: int
    question: str = "Why did AI move here?"


class WhyResponse(BaseModel):
    explanation: str
    evidence: list[str]
    alternatives: list[str] = []


class QARequest(BaseModel):
    question: str
    board: Optional[list[list[int]]] = None
    step_id: Optional[int] = None


class QAResponse(BaseModel):
    # type 可为：moves / qa / analysis / explanation
    type: str
    data: Any
    evidence: list[str] = []


class ReviewRequest(BaseModel):
    pass


class ReviewResponse(BaseModel):
    summary: str
    turning_points: list[str]
    mistakes: list[str]
    suggestions: list[str]
    evidence: list[str]
    winrate_series: list[dict]
    winner: Optional[str] = None
    total_steps: int = 0


class MoveRequest(BaseModel):
    board: list[list[int]]
    player: str


class MoveResponse(BaseModel):
    x: int
    y: int
    reasoning: str


class ValidateRequest(BaseModel):
    board: list[list[int]]
    x: int
    y: int


class ValidateResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None


class PersonalityResponse(BaseModel):
    personality_type: str
    title: str
    description: str
    strengths: list[str]
    risks: list[str]
    advice: list[str]
    fun_comment: str


# -----------------------------
# Helpers
# -----------------------------
def winner_to_text(winner: Optional[int]) -> Optional[str]:
    if winner == BLACK:
        return "human"
    if winner == WHITE:
        return "ai"
    return None


def _chunks_to_evidence(chunks: list[dict], limit: int = 4) -> list[str]:
    evidence: list[str] = []
    for chunk in chunks[:limit]:
        text = str(chunk.get("text", "")).strip()
        if text:
            evidence.append(text[:600])
    return evidence


def _latest_ai_step_id() -> Optional[int]:
    for record in reversed(current_session.history.records):
        if record.player == "ai":
            return record.step_id
    return None


def _heuristic_intent(question: str) -> str:
    q = question.lower()

    moves_keywords = [
        "下一步", "下哪里", "怎么走", "走哪里", "走哪", "推荐", "候选", "top3", "top 3",
        "best move", "next move", "where should", "what should i play",
    ]
    explanation_keywords = [
        "为什么", "为啥", "why", "解释", "这一步", "ai下", "ai move", "move here",
    ]
    analysis_keywords = [
        "分析", "局面", "局势", "优势", "劣势", "谁占优", "形势", "situation", "analyze", "advantage",
    ]

    if any(k in q for k in moves_keywords):
        return "moves"
    if any(k in q for k in explanation_keywords):
        return "explanation"
    if any(k in q for k in analysis_keywords):
        return "analysis"
    return "qa"


def classify_qa_intent(question: str) -> str:
    """先用规则兜底，再交给 llm_client.py 统一分类。"""
    heuristic = _heuristic_intent(question)
    if heuristic != "qa":
        return heuristic

    try:
        return get_llm_client().classify_question_intent(question)
    except Exception:
        return heuristic


def _evaluate_position(board: list[list[int]], x: int, y: int, player: int) -> int:
    opponent = WHITE if player == BLACK else BLACK
    directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
    score = 0

    for dx, dy in directions:
        my_count = 0
        opp_count = 0

        for step in range(1, 5):
            nx, ny = x + dx * step, y + dy * step
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == player:
                my_count += 1
            else:
                break

        for step in range(1, 5):
            nx, ny = x - dx * step, y - dy * step
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == player:
                my_count += 1
            else:
                break

        for step in range(1, 5):
            nx, ny = x + dx * step, y + dy * step
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == opponent:
                opp_count += 1
            else:
                break

        for step in range(1, 5):
            nx, ny = x - dx * step, y - dy * step
            if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == opponent:
                opp_count += 1
            else:
                break

        if my_count >= 4:
            score += 100000
        elif my_count == 3:
            score += 10000
        elif my_count == 2:
            score += 1000
        elif my_count == 1:
            score += 100

        if opp_count >= 4:
            score += 50000
        elif opp_count == 3:
            score += 5000
        elif opp_count == 2:
            score += 500

    center_bonus = max(0, 7 - abs(x - 7)) + max(0, 7 - abs(y - 7))
    return score + center_bonus


def _candidate_moves(board: list[list[int]]) -> set[tuple[int, int]]:
    candidates: set[tuple[int, int]] = set()
    has_stone = False

    for y in range(BOARD_SIZE):
        for x in range(BOARD_SIZE):
            if board[y][x] != EMPTY:
                has_stone = True
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == EMPTY:
                            candidates.add((nx, ny))

    if not has_stone:
        candidates.add((7, 7))
    return candidates


def _minimax_ai(board: list[list[int]], player: int) -> tuple[int, int, str]:
    best_score = -1
    best_moves: list[tuple[int, int]] = []
    candidates = _candidate_moves(board)

    for x, y in candidates:
        score = _evaluate_position(board, x, y, player)
        if score > best_score:
            best_score = score
            best_moves = [(x, y)]
        elif score == best_score:
            best_moves.append((x, y))

    x, y = random.choice(best_moves or [(7, 7)])

    if best_score >= 50000:
        reasoning = f"在 ({x}, {y}) 落子可以阻止对手的强威胁，或直接形成制胜线路。"
    elif best_score >= 10000:
        reasoning = f"在 ({x}, {y}) 落子可以加强当前的关键战术连续性。"
    elif best_score >= 1000:
        reasoning = f"在 ({x}, {y}) 落子可以提升局部进攻或防守效率。"
    else:
        reasoning = f"综合局面评估后，选择在 ({x}, {y}) 落子。"
    return x, y, reasoning


def _heuristic_top3_moves(board: list[list[int]], player: int = BLACK) -> dict:
    scored = []
    for x, y in _candidate_moves(board):
        attack_score = _evaluate_position(board, x, y, player)
        defense_score = _evaluate_position(board, x, y, WHITE if player == BLACK else BLACK)
        score = attack_score + int(defense_score * 0.9)
        scored.append((score, x, y, attack_score, defense_score))

    scored.sort(reverse=True, key=lambda item: item[0])
    top3 = []
    for rank, (score, x, y, attack_score, defense_score) in enumerate(scored[:3], start=1):
        if defense_score >= attack_score:
            reason = f"第{rank}推荐：优先处理对手威胁，同时保留己方后续连接空间。"
        else:
            reason = f"第{rank}推荐：增强己方局部连接，创造后续进攻延伸机会。"
        top3.append({"move": [y, x], "reason": reason})

    return {"top3": top3}


def _validate_top3_result(result: Any, board: list[list[int]]) -> dict:
    if not isinstance(result, dict):
        return _heuristic_top3_moves(board, BLACK)

    raw_items = result.get("top3", [])
    if not isinstance(raw_items, list):
        return _heuristic_top3_moves(board, BLACK)

    valid_items = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        move = item.get("move")
        if not isinstance(move, list) or len(move) != 2:
            continue
        try:
            row, col = int(move[0]), int(move[1])
        except Exception:
            continue
        if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
            continue
        if board[row][col] != EMPTY:
            continue
        if (row, col) in seen:
            continue
        seen.add((row, col))
        valid_items.append({
            "move": [row, col],
            "reason": str(item.get("reason", "推荐候选点")),
        })
        if len(valid_items) >= 3:
            break

    if valid_items:
        return {"top3": valid_items}
    return _heuristic_top3_moves(board, BLACK)


def build_personality_query(review_result: dict) -> str:
    style_profile = review_result.get("style_profile", {}) if isinstance(review_result.get("style_profile"), dict) else {}
    scores = style_profile.get("scores", {}) if isinstance(style_profile.get("scores"), dict) else {}
    primary = str(style_profile.get("primary_style", "均衡理性型"))
    secondary = str(style_profile.get("secondary_style", ""))
    reason = str(style_profile.get("reason", ""))

    text_parts = [review_result.get("summary", ""), primary, secondary, reason]
    for key in ["turning_points", "mistakes", "suggestions"]:
        values = review_result.get(key, [])
        if isinstance(values, list):
            text_parts.extend(str(v) for v in values[:3])

    if scores:
        text_parts.append(" ".join(f"{k}:{v}" for k, v in scores.items() if isinstance(v, (int, float))))

    merged = " ".join(text_parts).lower()
    return f"personality gomoku style aggressive defensive balanced risky opportunistic {merged}"


def build_review_query(key_moments: list[dict], review_signals: dict) -> str:
    terms = ["gomoku review", "mistakes", "defense", "threat", "attack", "open three", "open four", "connection"]

    pattern_counts = review_signals.get("pattern_counts", {}) if isinstance(review_signals, dict) else {}
    for key, count in pattern_counts.items():
        if not count:
            continue
        if key in {"missed_defense", "major_threat"}:
            terms.extend(["forced defense", "block threat"])
        elif key in {"pressure_build", "strong_attack"}:
            terms.extend(["pressure", "shape building"])
        elif key in {"winning_move", "ai_gain"}:
            terms.extend(["conversion", "finish attack"])

    for m in key_moments[:3]:
        summary = str(m.get("summary", ""))
        if "活三" in summary:
            terms.append("open three")
        if "冲四" in summary or "四连" in summary:
            terms.append("open four")

    return " ".join(dict.fromkeys(terms))


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
async def root():
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    raise HTTPException(status_code=404, detail="index.html not found")


@app.get("/api/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@app.post("/api/new-game", response_model=NewGameResponse)
async def new_game():
    current_session.reset()
    return NewGameResponse(
        board=current_session.game.board,
        current_player="black",
        game_over=False,
    )


@app.post("/api/play-turn", response_model=PlayTurnResponse)
async def play_turn(request: PlayTurnRequest):
    game = current_session.game
    history = current_session.history

    if game.game_over:
        raise HTTPException(status_code=400, detail="current game is already over")

    if not game.is_valid_move(request.x, request.y):
        raise HTTPException(status_code=400, detail="invalid human move")

    board_before_human = copy.deepcopy(game.board)
    game.make_move(request.x, request.y)

    human_eval_score = review_analyzer.evaluate_board_for_ai(game.board)
    human_record = history.record_move(
        player="human",
        x=request.x,
        y=request.y,
        board_before=board_before_human,
        board_after=game.board,
        reasoning=None,
        eval_score=human_eval_score,
    )

    if game.game_over:
        current_session.last_review_result = None
        return PlayTurnResponse(
            board=game.board,
            human_move={"x": request.x, "y": request.y, "step_id": human_record.step_id},
            ai_move=None,
            reasoning=None,
            winner=winner_to_text(game.winner),
            game_over=True,
        )

    if USE_LLM_FOR_AI_MOVE:
        try:
            ai_result = get_llm_client().generate_move(game.board, "white")
            ai_x = int(ai_result.get("x", 7))
            ai_y = int(ai_result.get("y", 7))
            ai_reasoning = str(ai_result.get("reasoning", ""))
        except Exception:
            ai_x, ai_y, ai_reasoning = _minimax_ai(game.board, WHITE)
    else:
        ai_x, ai_y, ai_reasoning = _minimax_ai(game.board, WHITE)

    if not game.is_valid_move(ai_x, ai_y):
        ai_x, ai_y, ai_reasoning = _minimax_ai(game.board, WHITE)

    board_before_ai = copy.deepcopy(game.board)
    game.make_move(ai_x, ai_y)

    ai_eval_score = review_analyzer.evaluate_board_for_ai(game.board)
    ai_record = history.record_move(
        player="ai",
        x=ai_x,
        y=ai_y,
        board_before=board_before_ai,
        board_after=game.board,
        reasoning=ai_reasoning,
        eval_score=ai_eval_score,
    )

    current_session.last_review_result = None

    return PlayTurnResponse(
        board=game.board,
        human_move={"x": request.x, "y": request.y, "step_id": human_record.step_id},
        ai_move={"x": ai_x, "y": ai_y, "step_id": ai_record.step_id},
        reasoning=ai_reasoning,
        winner=winner_to_text(game.winner),
        game_over=game.game_over,
    )


@app.post("/api/why", response_model=WhyResponse)
async def why_move(request: WhyRequest):
    history = current_session.history

    try:
        step_context = history.build_explain_context(request.step_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    query = f"{request.question} {step_context.get('reasoning', '')} defense threat center review tactics"
    chunks = retriever.retrieve(query, top_k=4)

    try:
        result = get_llm_client().generate_move_explanation(
            question=request.question,
            step_context=step_context,
            chunks=chunks,
        )
    except Exception:
        result = {
            "explanation": step_context.get("reasoning") or "AI 是根据当前棋形的攻防关系做出这一步选择的。",
            "evidence": _chunks_to_evidence(chunks, 2),
            "alternatives": [],
        }

    if "evidence" not in result:
        result["evidence"] = _chunks_to_evidence(chunks, 2)
    if "alternatives" not in result:
        result["alternatives"] = []

    return WhyResponse(**result)


@app.post("/api/qa", response_model=QAResponse)
async def qa(request: QARequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty question")

    board = request.board or current_session.game.board
    intent = classify_qa_intent(question)

    query = f"{question} gomoku rules tactics defense openings center attack review"
    if intent == "moves":
        query += " next move top3 candidate attack defense tactical priority"
    elif intent == "analysis":
        query += " board analysis advantage threat defense offense"
    elif intent == "explanation":
        query += " why move explanation evidence alternatives"

    chunks = retriever.retrieve(query, top_k=4)
    evidence = _chunks_to_evidence(chunks, 4)
    client = get_llm_client()

    if intent == "moves":
        try:
            result = client.generate_move_top3(question=question, board=board, current_player=BLACK, chunks=chunks)
            result = _validate_top3_result(result, board)
        except Exception:
            result = _heuristic_top3_moves(board, BLACK)
        return QAResponse(type="moves", data=result, evidence=evidence)

    if intent == "explanation":
        step_id = request.step_id or _latest_ai_step_id()
        if step_id is not None:
            try:
                step_context = current_session.history.build_explain_context(step_id)
                result = client.generate_move_explanation(question, step_context, chunks)
                return QAResponse(type="explanation", data=result, evidence=result.get("evidence", evidence))
            except Exception:
                pass

        fallback_answer = "目前还没有可解释的 AI 落子。请先下一步棋，等待 AI 落子后再询问为什么这样下。"
        return QAResponse(type="qa", data=fallback_answer, evidence=evidence)

    try:
        answer = client.generate_qa_answer(question, chunks, board=board, intent=intent)
    except Exception:
        if intent == "analysis":
            answer = "当前无法调用模型，但从规则上看，应优先检查是否存在直接成五、冲四、活三等强制威胁。"
        else:
            answer = "当前无法调用模型，但可以根据知识库先参考下方 evidence 中的规则解释。"

    return QAResponse(type=intent, data=answer, evidence=evidence)


@app.post("/api/review", response_model=ReviewResponse)
async def review_game(_: ReviewRequest):
    game = current_session.game
    history = current_session.history

    if not history.records:
        raise HTTPException(status_code=400, detail="No moves yet")

    review_context = history.build_review_context()
    review_context["winner"] = winner_to_text(game.winner)
    review_context["game_over"] = game.game_over

    key_moments = review_analyzer.extract_key_moments(history.records)
    winrate_series = review_analyzer.build_winrate_series(history.records)
    review_signals = review_analyzer.build_review_signals(history.records)
    style_profile = review_analyzer.build_style_profile(history.records)

    review_query = build_review_query(key_moments, review_signals)
    chunks = retriever.retrieve(review_query, top_k=4)

    review_payload = {
        "context": review_context,
        "key_moments": key_moments,
        "signals": review_signals,
        "style_profile": style_profile,
    }

    try:
        result = get_llm_client().generate_review(review_payload, chunks)
    except Exception:
        top_issue = review_signals.get("top_player_issue") if isinstance(review_signals, dict) else None
        top_issue_text = top_issue.get("summary") if isinstance(top_issue, dict) else ""
        result = {
            "summary": "这盘棋的关键在于关键威胁的处理顺序，以及中后段攻防转换的选择。",
            "turning_points": [m.get("summary", f"第{m.get('step_id')}步：局面波动明显。") for m in key_moments[:3]],
            "mistakes": [f"玩家最明显的问题是：{top_issue_text}"] if top_issue_text else ["玩家在关键阶段对强威胁的处理不够及时。"],
            "suggestions": ["先确认是否存在必须先挡的强威胁，再决定是否继续扩张自己的进攻。"],
            "evidence": _chunks_to_evidence(chunks, 2),
        }

    if "turning_points" not in result:
        result["turning_points"] = [m.get("summary", f"第{m.get('step_id')}步：局面波动明显。") for m in key_moments[:3]]
    if "mistakes" not in result:
        result["mistakes"] = []
    if "suggestions" not in result:
        result["suggestions"] = []
    if "evidence" not in result:
        result["evidence"] = _chunks_to_evidence(chunks, 2)

    public_review_result = {
        **result,
        "winrate_series": winrate_series,
        "winner": winner_to_text(game.winner) or "Draw",
        "total_steps": len(history.records),
    }

    current_session.last_review_result = {
        **public_review_result,
        "style_profile": style_profile,
        "review_signals": review_signals,
    }
    return ReviewResponse(**public_review_result)


@app.get("/api/download-report")
async def download_report():
    if current_session.last_review_result is None:
        raise HTTPException(status_code=400, detail="No review result available. Please generate review first.")

    report_md = report_exporter.build_markdown_report(current_session.last_review_result)

    return PlainTextResponse(
        report_md,
        headers={"Content-Disposition": "attachment; filename=gomoku_review_report.md"}
    )


@app.get("/api/history")
async def get_history():
    return {"history": current_session.history.get_history()}


@app.post("/api/move", response_model=MoveResponse)
async def make_move(request: MoveRequest):
    board = request.board
    player_str = request.player.lower()
    player = BLACK if player_str == "black" else WHITE

    if USE_LLM_FOR_AI_MOVE:
        try:
            result = get_llm_client().generate_move(board, player_str)
            x, y = int(result["x"]), int(result["y"])
            reasoning = str(result.get("reasoning", ""))
        except Exception:
            x, y, reasoning = _minimax_ai(board, player)
    else:
        x, y, reasoning = _minimax_ai(board, player)

    if board[y][x] != EMPTY:
        x, y, reasoning = _minimax_ai(board, player)

    return MoveResponse(x=x, y=y, reasoning=reasoning)


@app.post("/api/validate", response_model=ValidateResponse)
async def validate_move(request: ValidateRequest):
    game = GomokuGame(board=copy.deepcopy(request.board))
    if not (0 <= request.x < BOARD_SIZE and 0 <= request.y < BOARD_SIZE):
        return ValidateResponse(valid=False, reason="Out of bounds")
    if request.board[request.y][request.x] != EMPTY:
        return ValidateResponse(valid=False, reason="Cell is already occupied")
    if game.game_over:
        return ValidateResponse(valid=False, reason="Game is already over")
    return ValidateResponse(valid=True)


@app.post("/api/personality-test", response_model=PersonalityResponse)
async def personality_test():
    if current_session.last_review_result is None:
        raise HTTPException(status_code=400, detail="No review result available. Please generate review first.")

    review_result = current_session.last_review_result
    if "style_profile" not in review_result:
        review_result["style_profile"] = review_analyzer.build_style_profile(current_session.history.records)

    query = build_personality_query(review_result)
    chunks = retriever.retrieve(query, top_k=4)

    try:
        result = get_llm_client().generate_personality_test(review_result, chunks)
    except Exception:
        result = get_llm_client()._build_personality_from_style_profile(
            review_result.get("style_profile", {}),
            review_result,
        )

    return PersonalityResponse(**result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
