
"""Review analyzer: key moments, win-rate approximation, and style profile."""

from __future__ import annotations

from typing import Dict, List, Tuple
from game import BLACK, WHITE, BOARD_SIZE, EMPTY


class ReviewAnalyzer:
    def __init__(self) -> None:
        self.directions = [(1, 0), (0, 1), (1, 1), (1, -1)]

    # -----------------------------
    # Public API
    # -----------------------------
    def evaluate_board_for_ai(self, board: List[List[int]]) -> float:
        """
        Evaluate board from AI (white) perspective.

        Positive score => AI better
        Negative score => human better

        Uses pattern counting over the whole board instead of piece-by-piece
        accumulation to reduce duplicated counting and make win-rate curves
        more meaningful.
        """
        ai_features = self._board_pattern_stats(board, WHITE)
        human_features = self._board_pattern_stats(board, BLACK)

        ai_score = self._feature_score(ai_features)
        human_score = self._feature_score(human_features)

        score = ai_score - human_score
        # keep score in a moderate range so win-rate mapping stays smooth
        return max(-18.0, min(18.0, round(score, 2)))

    def extract_key_moments(self, full_records: List) -> List[Dict]:
        if not full_records:
            return []

        candidates: List[Dict] = []
        prev_score = 0.0
        last_idx = len(full_records) - 1

        for idx, record in enumerate(full_records):
            curr_score = float(record.eval_score or 0.0)
            delta = curr_score - prev_score
            prev_score = curr_score

            move_features = self._analyze_move_features(record)
            importance = abs(delta)
            if move_features["has_five"]:
                importance += 10
            if move_features["open_four"]:
                importance += 6
            elif move_features["closed_four"]:
                importance += 3.5
            elif move_features["open_three"]:
                importance += 2.2

            before_threat = self._board_threat_level(record.board_before, WHITE if record.player == "human" else BLACK)
            after_threat = self._board_threat_level(record.board_after, WHITE if record.player == "human" else BLACK)
            if after_threat > before_threat:
                importance += 1.0

            if idx == 0 or idx == last_idx:
                importance += 0.6

            keep = (
                abs(delta) >= 2.0
                or move_features["has_five"]
                or move_features["open_four"]
                or move_features["open_three"]
                or idx == last_idx
            )
            if not keep:
                continue

            moment_type = self._classify_moment_type(record.player, delta, move_features, before_threat, after_threat)
            summary = self._build_moment_summary(record.step_id, record.player, delta, moment_type, move_features)

            candidates.append(
                {
                    "step_id": record.step_id,
                    "player": record.player,
                    "move": {"x": record.x, "y": record.y},
                    "delta": round(delta, 2),
                    "impact": round(importance, 2),
                    "moment_type": moment_type,
                    "reasoning": record.reasoning or "",
                    "summary": summary,
                }
            )

        if not candidates:
            return []

        top = sorted(candidates, key=lambda m: (-float(m.get("impact", 0)), int(m.get("step_id", 0))))[:5]
        top.sort(key=lambda m: int(m.get("step_id", 0)))
        return top

    def build_winrate_series(self, full_records: List) -> List[Dict]:
        series: List[Dict] = []
        for record in full_records:
            score = float(record.eval_score or 0.0)
            winrate_ai = self._score_to_winrate(score)
            series.append(
                {
                    "step": record.step_id,
                    "winrate_ai": round(winrate_ai, 1),
                    "player": record.player,
                }
            )
        return series

    def build_review_signals(self, full_records: List) -> Dict:
        key_moments = self.extract_key_moments(full_records)

        human_bad_steps = []
        human_good_steps = []
        ai_good_steps = []
        pressure_steps = []

        pattern_counts: Dict[str, int] = {}
        for item in key_moments:
            moment_type = item.get("moment_type", "swing")
            pattern_counts[moment_type] = pattern_counts.get(moment_type, 0) + 1

            if moment_type in {"human_mistake", "missed_defense"}:
                human_bad_steps.append(item)
            elif moment_type in {"human_improvement", "player_attack"}:
                human_good_steps.append(item)
            elif moment_type in {"ai_gain", "winning_move", "ai_attack"}:
                ai_good_steps.append(item)

            if moment_type in {"player_attack", "ai_attack", "major_threat", "pressure_build"}:
                pressure_steps.append(item)

        top_player_issue = human_bad_steps[0] if human_bad_steps else None
        top_player_good = human_good_steps[0] if human_good_steps else None

        return {
            "key_moments": key_moments,
            "pattern_counts": pattern_counts,
            "human_bad_steps": human_bad_steps[:3],
            "human_good_steps": human_good_steps[:3],
            "ai_good_steps": ai_good_steps[:3],
            "pressure_steps": pressure_steps[:3],
            "top_player_issue": top_player_issue,
            "top_player_good": top_player_good,
        }

    def build_style_profile(self, full_records: List) -> Dict:
        human_records = [r for r in full_records if r.player == "human"]
        if not human_records:
            return {
                "primary_style": "均衡理性型",
                "secondary_style": "慢热成长型",
                "scores": {
                    "attack": 50,
                    "defense": 50,
                    "risk": 35,
                    "balance": 55,
                    "opportunism": 45,
                    "center": 50,
                },
                "reason": "样本不足，先按均衡型处理。",
            }

        attack = defense = risk = opportunity = center = 0.0

        for r in human_records:
            x, y = r.x, r.y
            center += max(0.0, 8.0 - (abs(x - 7) + abs(y - 7)) * 0.8)

            before_ai = self._board_threat_level(r.board_before, WHITE)
            after_ai = self._board_threat_level(r.board_after, WHITE)
            after_human = self._board_threat_level(r.board_after, BLACK)

            move_features = self._analyze_move_features(r)

            if before_ai >= 3:
                defense += 2.2
                if after_ai < before_ai:
                    defense += 2.3
                else:
                    risk += 2.0

            if move_features["has_five"]:
                attack += 4.5
            elif move_features["open_four"]:
                attack += 3.2
            elif move_features["closed_four"]:
                attack += 2.4
            elif move_features["open_three"]:
                attack += 1.8
            elif after_human > 0:
                attack += 0.8

            if before_ai <= 1 and after_human >= 3:
                opportunity += 1.8

        n = max(1, len(human_records))
        attack_s = min(100, round(25 + attack / n * 18))
        defense_s = min(100, round(25 + defense / n * 18))
        risk_s = min(100, round(15 + risk / n * 20))
        opportunity_s = min(100, round(20 + opportunity / n * 18))
        center_s = min(100, round(center / n * 12))
        balance_s = max(0, min(100, round(100 - abs(attack_s - defense_s) * 1.2 - risk_s * 0.25 + 10)))

        scores = {
            "attack": attack_s,
            "defense": defense_s,
            "risk": risk_s,
            "balance": balance_s,
            "opportunism": opportunity_s,
            "center": center_s,
        }

        if risk_s >= 68 and attack_s >= 58:
            primary = "冲动冒险型"
            secondary = "激进进攻型"
            reason = "多次在高压局面下仍主动求变，风险偏好较明显。"
        elif defense_s - attack_s >= 12:
            primary = "稳健防守型"
            secondary = "均衡理性型"
            reason = "更重视先处理威胁，再考虑扩张。"
        elif attack_s - defense_s >= 12 and risk_s < 62:
            primary = "激进进攻型"
            secondary = "机会主义型"
            reason = "主动制造进攻压力的倾向更明显。"
        elif opportunity_s >= 62:
            primary = "机会主义型"
            secondary = "均衡理性型"
            reason = "更擅长抓住局部机会形成突破。"
        elif len(human_records) <= 7:
            primary = "慢热成长型"
            secondary = "均衡理性型"
            reason = "样本较少，整体更像边下边调整。"
        else:
            primary = "均衡理性型"
            secondary = "稳健防守型" if defense_s >= attack_s else "激进进攻型"
            reason = "攻防倾向接近，整体风格较平衡。"

        return {
            "primary_style": primary,
            "secondary_style": secondary,
            "scores": scores,
            "reason": reason,
        }

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _board_pattern_stats(self, board: List[List[int]], player: int) -> Dict[str, int]:
        stats = {
            "five": 0,
            "open_four": 0,
            "closed_four": 0,
            "open_three": 0,
            "closed_three": 0,
            "open_two": 0,
            "center_stones": 0,
        }
        center = BOARD_SIZE // 2

        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                if board[y][x] != player:
                    continue

                if abs(x - center) + abs(y - center) <= 3:
                    stats["center_stones"] += 1

                for dx, dy in self.directions:
                    px, py = x - dx, y - dy
                    if 0 <= px < BOARD_SIZE and 0 <= py < BOARD_SIZE and board[py][px] == player:
                        continue

                    count, open_ends = self._line_features(board, x, y, player, dx, dy)
                    if count >= 5:
                        stats["five"] += 1
                    elif count == 4 and open_ends == 2:
                        stats["open_four"] += 1
                    elif count == 4 and open_ends == 1:
                        stats["closed_four"] += 1
                    elif count == 3 and open_ends == 2:
                        stats["open_three"] += 1
                    elif count == 3 and open_ends == 1:
                        stats["closed_three"] += 1
                    elif count == 2 and open_ends == 2:
                        stats["open_two"] += 1

        return stats

    def _feature_score(self, stats: Dict[str, int]) -> float:
        return (
            stats["five"] * 20.0
            + stats["open_four"] * 7.5
            + stats["closed_four"] * 4.5
            + stats["open_three"] * 2.2
            + stats["closed_three"] * 1.0
            + stats["open_two"] * 0.4
            + stats["center_stones"] * 0.15
        )

    def _analyze_move_features(self, record) -> Dict[str, bool]:
        board = record.board_after
        x, y = record.x, record.y
        player = WHITE if record.player == "ai" else BLACK

        has_five = False
        open_four = False
        closed_four = False
        open_three = False

        for dx, dy in self.directions:
            count, open_ends = self._line_features(board, x, y, player, dx, dy)
            if count >= 5:
                has_five = True
            elif count == 4 and open_ends == 2:
                open_four = True
            elif count == 4 and open_ends == 1:
                closed_four = True
            elif count == 3 and open_ends == 2:
                open_three = True

        return {
            "has_five": has_five,
            "open_four": open_four,
            "closed_four": closed_four,
            "open_three": open_three,
        }

    def _board_threat_level(self, board: List[List[int]], player: int) -> int:
        stats = self._board_pattern_stats(board, player)
        if stats["five"] > 0:
            return 5
        if stats["open_four"] > 0:
            return 4
        if stats["closed_four"] > 0:
            return 3
        if stats["open_three"] > 0:
            return 2
        if stats["closed_three"] > 0 or stats["open_two"] > 0:
            return 1
        return 0

    def _line_features(self, board: List[List[int]], x: int, y: int, player: int, dx: int, dy: int) -> Tuple[int, int]:
        count = 1
        open_ends = 0

        nx, ny = x + dx, y + dy
        while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == player:
            count += 1
            nx += dx
            ny += dy
        if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == EMPTY:
            open_ends += 1

        nx, ny = x - dx, y - dy
        while 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == player:
            count += 1
            nx -= dx
            ny -= dy
        if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and board[ny][nx] == EMPTY:
            open_ends += 1

        return count, open_ends

    def _classify_moment_type(
        self,
        player: str,
        delta: float,
        features: Dict[str, bool],
        before_threat: int,
        after_threat: int,
    ) -> str:
        if features["has_five"]:
            return "winning_move"
        if features["open_four"]:
            return "major_threat"
        if features["closed_four"]:
            return "strong_attack"
        if features["open_three"]:
            return "pressure_build"

        if player == "human":
            if delta <= -2.0:
                return "human_improvement"
            if delta >= 2.0:
                if before_threat >= 3 and after_threat >= before_threat:
                    return "missed_defense"
                return "human_mistake"
        else:
            if delta >= 2.0:
                return "ai_gain"
            if delta <= -2.0:
                return "ai_miss"
        return "swing"

    def _build_moment_summary(
        self,
        step_id: int,
        player: str,
        delta: float,
        moment_type: str,
        features: Dict[str, bool],
    ) -> str:
        side = "AI" if player == "ai" else "玩家"
        if moment_type == "winning_move":
            return f"第{step_id}步：{side}这一步形成成五，基本决定了胜负。"
        if moment_type == "major_threat":
            return f"第{step_id}步：{side}这一步形成了强制性冲四威胁。"
        if moment_type == "strong_attack":
            return f"第{step_id}步：{side}这一步把局部推进到四连附近，压力明显增大。"
        if moment_type == "pressure_build":
            return f"第{step_id}步：{side}这一步建立了活三级别的进攻潜力。"
        if moment_type == "human_improvement":
            return f"第{step_id}步：玩家这一步明显改善了局面。"
        if moment_type == "missed_defense":
            return f"第{step_id}步：玩家这一步没有优先化解对手的强威胁。"
        if moment_type == "human_mistake":
            return f"第{step_id}步：玩家这一步后局面对自己变得更不利。"
        if moment_type == "ai_gain":
            return f"第{step_id}步：AI 这一步后局面明显向 AI 一侧倾斜。"
        if moment_type == "ai_miss":
            return f"第{step_id}步：AI 这一步并没有延续最佳压制节奏。"
        return f"第{step_id}步：{side}落子后局面波动明显。"

    @staticmethod
    def _score_to_winrate(score: float) -> float:
        # Smooth logistic-like mapping without saturating too early
        import math
        return max(3.0, min(97.0, 50.0 + 46.0 * math.tanh(score / 7.5)))
