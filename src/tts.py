"""edge-tts로 대본 → 음성(mp3) + 단어별 타이밍(json).

단독 실행:
    .venv/bin/python -m src.tts samples/sample_01.txt output/_work/tts_test
"""
import argparse
import asyncio
import json
from pathlib import Path

import edge_tts

from src import config


async def _synthesize(text: str, voice: str, rate: str, mp3_path: Path) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7  # 100ns 단위 → 초
                words.append({
                    "text": chunk["text"],
                    "start": round(start, 3),
                    "end": round(start + chunk["duration"] / 1e7, 3),
                })
    return words


def _restore_punctuation(text: str, words: list[dict]) -> None:
    """edge-tts 단어에는 문장부호가 빠져 있어서, 원문에서 찾아 붙여 준다 (예: 잡니다 → 잡니다.)."""
    cursor = 0
    for w in words:
        idx = text.find(w["text"], cursor)
        if idx < 0:  # 숫자 읽기 등으로 원문과 다르면 그대로 둠
            continue
        end = idx + len(w["text"])
        while end < len(text) and not text[end].isspace():
            end += 1
        w["text"] = text[idx:end]
        cursor = end


def synthesize(text: str, out_dir: Path, voice: str | None = None, rate: str | None = None) -> tuple[Path, Path]:
    """음성과 타이밍 파일을 out_dir에 만들고 (mp3 경로, json 경로)를 돌려준다."""
    cfg = config.load()["voice"]
    voice = voice or cfg["name"]
    rate = rate or cfg["rate"]
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / "voice.mp3"
    json_path = out_dir / "words.json"

    text = " ".join(text.split())  # 줄바꿈·연속 공백 정리
    words = asyncio.run(_synthesize(text, voice, rate, mp3_path))
    if not words:
        raise RuntimeError("edge-tts가 단어 타이밍을 주지 않았습니다.")
    _restore_punctuation(text, words)
    json_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    return mp3_path, json_path


def main():
    ap = argparse.ArgumentParser(description="대본 txt → 음성 mp3 + 단어 타이밍 json")
    ap.add_argument("script", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--voice")
    ap.add_argument("--rate")
    args = ap.parse_args()
    mp3, js = synthesize(args.script.read_text(encoding="utf-8"), args.out_dir, args.voice, args.rate)
    words = json.loads(js.read_text(encoding="utf-8"))
    print(f"음성: {mp3}\n타이밍: {js} ({len(words)}단어, {words[-1]['end']:.1f}초)")


if __name__ == "__main__":
    main()
