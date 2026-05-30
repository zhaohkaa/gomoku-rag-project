from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_KNOWLEDGE = [
    {
        "id": "k1",
        "topic": "defense",
        "keywords": ["block", "defense", "open four", "threat"],
        "text": "If the opponent has an open four, blocking is usually mandatory.",
    },
    {
        "id": "k2",
        "topic": "center",
        "keywords": ["center", "opening", "influence"],
        "text": "Control near the center usually gives more extension options in Gomoku.",
    },
    {
        "id": "k3",
        "topic": "attack",
        "keywords": ["three", "double threat", "fork"],
        "text": "Building connected threats can force the opponent into passive defense.",
    },
    {
        "id": "k4",
        "topic": "review",
        "keywords": ["review", "mistake", "missed defense"],
        "text": "A common mistake is expanding attack while ignoring an immediate defensive response.",
    },
    {
        "id": "k5",
        "topic": "endgame",
        "keywords": ["win", "winning", "forced"],
        "text": "When a forced winning line appears, prioritizing it is often stronger than positional expansion.",
    },
]


def extract_keywords(text):
    keywords = []

    if "活三" in text or "open three" in text:
        keywords.append("three")

    if "冲四" in text or "open four" in text:
        keywords.append("four")

    if "防守" in text:
        keywords.append("defense")

    if "中心" in text:
        keywords.append("center")

    return keywords


class RAGRetriever:
    def __init__(self, knowledge_path: Path) -> None:
        self.knowledge_path = knowledge_path
        # self.chunks = self._load_chunks()
        old_chunks = self._load_chunks()
        BASE_DIR = Path(__file__).resolve().parent
        new_chunks = self.load_md_as_chunks(BASE_DIR / "knowledge_raw")

        # 合并新旧chunks
        self.chunks = new_chunks + old_chunks

    def _load_chunks(self) -> List[Dict[str, Any]]:
        if self.knowledge_path.exists():
            try:
                return json.loads(self.knowledge_path.read_text(encoding="utf-8"))
            except Exception:
                return DEFAULT_KNOWLEDGE
        return DEFAULT_KNOWLEDGE

    def load_md_as_chunks(self, folder_path):
        chunks = []

        for file in os.listdir(folder_path):
            if file.endswith(".md"):
                path = os.path.join(folder_path, file)

                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                sections = re.split(r"\n#{1,6}\s+", content)

                for sec in sections:
                    sec = sec.strip()
                    if len(sec) < 30:
                        continue

                    chunks.append(
                        {
                            "id": f"{file}_{len(chunks)}",
                            "topic": file.replace(".md", ""),
                            "keywords": extract_keywords(sec),
                            "text": sec,
                        }
                    )

        return chunks

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        q = query.lower()
        scored = []

        for chunk in self.chunks:
            score = 0

            topic = chunk.get("topic", "").lower()
            if topic and topic in q:
                score += 2

            for kw in chunk.get("keywords", []):
                if kw.lower() in q:
                    score += 3

            if score > 0:
                scored.append((score, chunk))

        if not scored:
            return self.chunks[:top_k]

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]
