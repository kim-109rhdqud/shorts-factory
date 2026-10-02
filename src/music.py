"""배경음악 고르기 + 출처 문구.

단독 실행 (풀에서 한 곡 골라 보기):
    .venv/bin/python -m src.music bright
"""
import argparse
import random
from pathlib import Path

from src import config
from src.fetch_assets import MUSIC_DIR, music_sources


def pick(pool: str, rng: random.Random | None = None) -> Path | None:
    """풀 폴더에서 mp3 하나를 무작위로. 없으면 None (음악 없이 진행)."""
    files = sorted((MUSIC_DIR / pool).glob("*.mp3"))
    return (rng or random).choice(files) if files else None


def credit(track: Path) -> str:
    """영상 설명에 넣을 출처 문구 (CC BY 4.0 표기)."""
    src = music_sources()
    return f'Music: "{track.stem}" {src["author"]}\n{src["license"]}'


def main():
    ap = argparse.ArgumentParser(description="배경음악 한 곡 고르기")
    ap.add_argument("pool", nargs="?", default=config.load()["music"]["pool"])
    args = ap.parse_args()
    track = pick(args.pool)
    print(f"선택: {track}\n\n{credit(track)}" if track else "이 풀에 곡이 없습니다.")


if __name__ == "__main__":
    main()
