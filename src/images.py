"""장면 그림 만들기: Antigravity CLI의 이미지 생성 기능 (Google AI Pro 구독 범위, 추가 비용 없음).

- 한 번 호출로 장면 그림 여러 장 (scene1, scene2, ...). 다시 그리기 금지 지시 (시간·사용량 절약)
- agy는 파일 편집만 허락(--mode accept-edits), 명령 실행은 막힘. 프로젝트 밖 빈 폴더에서 실행
- agy는 그림을 자기 작업 폴더(~/.gemini/antigravity-cli/brain/<대화ID>/)에 저장 → 거기서 찾아 복사
- 하루 그림 상한 (config.yaml images.daily_limit)

단독 실행:
    .venv/bin/python -m src.images output/_work/img_test "a cat sleeping on a sofa" "the cat waking up surprised"
"""
import argparse
import datetime as dt
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from src import config

log = logging.getLogger("images")

BRAIN = Path("~/.gemini/antigravity-cli/brain").expanduser()


class ImageError(RuntimeError):
    pass


def _cfg() -> dict:
    return config.load()["images"]


def _usage_today() -> int:
    f = config.path(_cfg()["usage_file"])
    data = json.loads(f.read_text()) if f.exists() else {}
    return data.get(dt.date.today().isoformat(), 0)


def _add_usage(n: int) -> None:
    f = config.path(_cfg()["usage_file"])
    today = dt.date.today().isoformat()
    data = json.loads(f.read_text()) if f.exists() else {}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({today: data.get(today, 0) + n}))


def build_prompt(descriptions: list[str], art_style: str, characters: str = "") -> str:
    lines = [f"{i}) scene{i}: {d}" for i, d in enumerate(descriptions, 1)]
    return (
        f"Generate {len(descriptions)} separate images, vertical 9:16, all in exactly the same art style: {art_style}.\n"
        "Absolutely no text, letters, numbers, sound effects or speech bubbles anywhere in the images. "
        "Screens and papers must show only blurred or abstract shapes.\n"
        + (f"Keep these characters looking identical in every image: {characters}\n" if characters else "")
        + "\n".join(lines)
        + "\nSave them as " + ", ".join(f"scene{i}" for i in range(1, len(descriptions) + 1)) + ". "
        "Generate each image exactly once. Do not review, revise or regenerate any image. "
        "Do not run any shell commands. When all are saved, reply DONE."
    )


def _find_outputs(conversation_id: str, n: int) -> list[Path | None]:
    """대화 폴더(와 그 하위 에이전트 폴더)에서 sceneN 그림을 찾는다. 같은 장면이 여러 장이면 가장 최근 것."""
    folders = [BRAIN / conversation_id]
    sub = BRAIN / conversation_id / ".system_generated" / "subagents"
    if sub.exists():
        folders += [BRAIN / p.stem for p in sub.glob("*.json")]
    files = [f for d in folders if d.exists() for f in d.iterdir()
             if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    found = []
    for i in range(1, n + 1):
        matches = [f for f in files if re.match(rf"scene{i}(?:_|\.|$)", f.name)]
        found.append(max(matches, key=lambda f: f.stat().st_mtime) if matches else None)
    return found


def generate(descriptions: list[str], out_dir: Path, art_style: str, characters: str = "") -> list[Path | None]:
    """장면 설명들 → out_dir/scene{i}.jpg. 못 만든 장면은 None."""
    n = len(descriptions)
    if _usage_today() + n > _cfg()["daily_limit"]:
        raise ImageError(f"오늘 그림 상한({_cfg()['daily_limit']}장) 초과")
    sandbox = config.path(config.load()["llm"]["sandbox"])
    sandbox.mkdir(parents=True, exist_ok=True)
    cmd = [config.tool("agy"), "-p", build_prompt(descriptions, art_style, characters), "--mode", "accept-edits",
           "--output-format", "json", "--print-timeout", f"{_cfg()['timeout_sec'] - 30}s"]
    _add_usage(n)
    try:
        proc = subprocess.run(cmd, cwd=sandbox, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=_cfg()["timeout_sec"])
    except subprocess.TimeoutExpired:
        raise ImageError("그림 생성 시간 초과")
    try:
        conv = json.loads(proc.stdout)["conversation_id"]
    except (json.JSONDecodeError, KeyError):
        raise ImageError(f"agy 응답을 읽을 수 없음: {proc.stdout[-300:]} {proc.stderr[-300:]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, src in enumerate(_find_outputs(conv, n), 1):
        if src is None:
            results.append(None)
            continue
        dest = out_dir / f"scene{i}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        results.append(dest)
    log.info("그림 %d/%d장 생성", sum(r is not None for r in results), n)
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="장면 그림 생성 테스트")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("descriptions", nargs="+")
    ap.add_argument("--style", default="Korean webtoon illustration, clean line art, soft cel shading")
    args = ap.parse_args()
    for p in generate(args.descriptions, args.out_dir, args.style):
        print(p)


if __name__ == "__main__":
    main()
