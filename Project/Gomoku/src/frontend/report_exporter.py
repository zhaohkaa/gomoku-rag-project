"""Report exporter for Gomoku game review results."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict


class ReportExporter:
    @staticmethod
    def build_markdown_report(review_result: Dict[str, Any]) -> str:
        summary = review_result.get("summary", "无总结")
        turning_points = review_result.get("turning_points", [])
        mistakes = review_result.get("mistakes", [])
        suggestions = review_result.get("suggestions", [])
        evidence = review_result.get("evidence", [])
        winrate_series = review_result.get("winrate_series", [])
        winner = review_result.get("winner", "未知")
        total_steps = review_result.get("total_steps", 0)

        def bullet(items):
            if not items:
                return "- 无"
            return "\n".join(f"- {item}" for item in items)

        trend_lines = "\n".join(
            f"- 第 {item['step']} 步 ({'黑' if item['player']=='human' else '白'}): AI 胜率 {item['winrate_ai']}%"
            for item in winrate_series
        ) or "- 无数据"

        return f"""# 五子棋对局复盘报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 游戏概览
- 获胜方: {winner}
- 总步数: {total_steps}

## 核心总结
{summary}

## 关键转折点
{bullet(turning_points)}

## 失误分析
{bullet(mistakes)}

## 改进建议
{bullet(suggestions)}

## 策略依据 (RAG)
{bullet(evidence)}

## 胜率走势
{trend_lines}
"""

    @staticmethod
    def build_json_report(review_result: Dict[str, Any]) -> str:
        return json.dumps(review_result, ensure_ascii=False, indent=2)
