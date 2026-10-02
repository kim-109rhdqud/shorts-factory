"""공통 설정 읽기: config.yaml + .env(비밀 정보) + 경로 도우미."""
import os
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


@lru_cache
def _dotenv() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def secret(name: str) -> str:
    """비밀 정보 (.env 또는 환경변수). 없으면 오류."""
    value = os.environ.get(name) or _dotenv().get(name)
    if not value:
        raise RuntimeError(f"{name} 이(가) .env에 없습니다.")
    return value
