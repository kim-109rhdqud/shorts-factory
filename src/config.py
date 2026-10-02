"""공통 설정 읽기: config.yaml + 경로 도우미."""
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache
def load() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(rel: str) -> Path:
    """프로젝트 폴더 기준 경로 → 절대 경로."""
    p = Path(rel).expanduser()
    return p if p.is_absolute() else ROOT / p


def tool(name: str) -> str:
    """외부 프로그램 실행 파일 경로 (~ 확장)."""
    value = load()["tools"][name]
    return str(Path(value).expanduser()) if "/" in value else value
