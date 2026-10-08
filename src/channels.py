"""채널 설정 (channels/<채널ID>.yaml) 읽기.

채널 하나 = 파일 하나. 파일이 없는 채널(예: test)은 config.yaml의 기본값으로 동작한다.

단독 실행 (채널 목록과 설정 보기):
    .venv/bin/python -m src.channels
"""
from pathlib import Path

import yaml

from src import config

CHANNEL_DIR = config.path("channels")


def list_ids(include_inactive: bool = False) -> list[str]:
    """채널 ID 목록. priority가 작은 채널부터 (없으면 9), 같으면 이름순. active: false인 채널은 뺌."""
    ids = sorted(p.stem for p in CHANNEL_DIR.glob("*.yaml"))
    if not include_inactive:
        ids = [c for c in ids if load(c).get("active", True)]
    return sorted(ids, key=lambda c: load(c).get("priority", 9))


def load(channel_id: str) -> dict:
    """채널 설정. 파일이 없으면 기본값만 담은 dict."""
    f = CHANNEL_DIR / f"{channel_id}.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
    data["id"] = channel_id
    data.setdefault("name", channel_id)
    data.setdefault("styles", ["trivia"])
    data.setdefault("daily_count", 0)
    data.setdefault("banned_topics", [])
    return data


def voice_for(ch: dict, narrator: str | None = None) -> tuple[str | None, str | None, str | None]:
    """(목소리, 속도, 높낮이). 채널에 화자별 목소리(voices)가 있으면 narrator로 고른다. 없는 값은 None(기본값 사용)."""
    voice = ch.get("voices", {}).get(narrator) if narrator else None
    return voice or ch.get("voice"), ch.get("speech_rate"), ch.get("voice_pitch")


def main():
    for cid in list_ids():
        ch = load(cid)
        print(f"{cid}: {ch['name']} / 스타일 {ch['styles']} / 하루 {ch['daily_count']}개 / 목소리 {ch.get('voice') or ch.get('voices')}")


if __name__ == "__main__":
    main()
