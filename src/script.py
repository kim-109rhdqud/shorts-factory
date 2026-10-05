"""주제 → 대본·제목·설명·해시태그 (JSON) 생성 + 검사.

검사: JSON 형식, 필수 항목, 대본 길이, 금지 주제, 배경·음악 풀 이름. 통과 못 하면 이유를 붙여 다시 요청.

단독 실행:
    .venv/bin/python -m src.script "문어의 심장" --out output/_work/script_test.json
"""
import argparse
import json
import logging
import re
from pathlib import Path

import yaml

from src import config, llm

log = logging.getLogger("script")

REQUIRED = ("title", "script", "description", "hashtags", "background_pool", "music_pool", "fact_check")


def _pools() -> tuple[list[str], list[str]]:
    bg = yaml.safe_load(config.path("assets/backgrounds/sources.yaml").read_text(encoding="utf-8"))["pools"]
    music = yaml.safe_load(config.path("assets/music/sources.yaml").read_text(encoding="utf-8"))["pools"]
    return list(bg), list(music)


def build_prompt(topic: str, style: str = "trivia") -> str:
    cfg = config.load()["script"]
    bg_pools, music_pools = _pools()
    template = (config.path(cfg["template_dir"]) / style / "prompt.md").read_text(encoding="utf-8")
    return template.format(
        topic=topic, min_chars=cfg["min_chars"], max_chars=cfg["max_chars"],
        banned_topics=", ".join(cfg["banned_topics"]),
        background_pools=", ".join(bg_pools), music_pools=", ".join(music_pools),
    )


def extract_json(text: str) -> dict:
    """답변에서 JSON 객체 하나를 꺼낸다 (앞뒤 잡담·코드블록이 붙어 있어도)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("JSON이 없음")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def script_length(script: str) -> int:
    return len(re.sub(r"\s", "", script))


def validate(data: dict, topic: str) -> list[str]:
    """문제 목록 (비어 있으면 통과)."""
    cfg = config.load()["script"]
    bg_pools, music_pools = _pools()
    problems = [f"'{k}' 항목 없음" for k in REQUIRED if k not in data]
    if problems:
        return problems
    script = data["script"].strip()
    if not script:
        return ["금지 주제로 판단되어 대본이 비어 있음"]
    n = script_length(script)
    if not cfg["min_chars"] <= n <= cfg["max_chars"]:
        problems.append(f"대본 길이 {n}자 (공백 제외 {cfg['min_chars']}~{cfg['max_chars']}자여야 함)")
    for word in cfg["banned_topics"]:
        if word in topic or word in script:
            problems.append(f"금지 주제 단어 포함: {word}")
    if re.search(r"[()\[\]<>{}#*_~]|[\U0001F300-\U0001FAFF]", script):
        problems.append("대본에 괄호·특수기호·이모지가 있음 (TTS용이라 빼야 함)")
    counted = re.findall(r"(?<![\d.,])(\d{1,2})\s?(개|명|마리|살|번|시간|가지)", script)
    if counted:
        examples = ", ".join(n + c for n, c in counted[:3])
        problems.append(f"세는 말 앞 작은 수를 숫자로 씀 ({examples}) → '세 개'처럼 한글로")
    if script.startswith(("안녕하세요", "오늘은", "여러분")):
        problems.append("첫 문장이 인사·소개로 시작함 (바로 훅으로 시작해야 함)")
    if data["background_pool"] not in bg_pools:
        problems.append(f"background_pool은 {bg_pools} 중 하나여야 함")
    if data["music_pool"] not in music_pools:
        problems.append(f"music_pool은 {music_pools} 중 하나여야 함")
    if not isinstance(data["hashtags"], list) or not isinstance(data["fact_check"], list):
        problems.append("hashtags와 fact_check는 목록이어야 함")
    return problems


def review(data: dict) -> dict:
    """두 번째 호출: 사실 오류·과장·상투적 표현을 고친다. 고친 결과가 검사에 떨어지면 원래 것을 쓴다."""
    cfg = config.load()["script"]
    bg_pools, music_pools = _pools()
    draft = {k: data[k] for k in REQUIRED}
    template = (config.path(cfg["template_dir"]) / "_review.md").read_text(encoding="utf-8")
    prompt = template.format(
        draft=json.dumps(draft, ensure_ascii=False, indent=1), min_chars=cfg["min_chars"],
        max_chars=cfg["max_chars"], background_pools=", ".join(bg_pools), music_pools=", ".join(music_pools),
    )
    try:
        text, provider = llm.generate(prompt)
        fixed = extract_json(text)
        problems = validate(fixed, data["topic"])
    except (ValueError, llm.LLMError) as e:
        problems = [str(e)]
    if problems:
        log.warning("검토 결과 사용 안 함 (원래 대본 유지): %s", "; ".join(problems))
        return data
    fixed["script"] = fixed["script"].strip()
    return {**data, **{k: fixed[k] for k in REQUIRED}, "reviewed_by": provider, "draft_script": data["script"]}


def generate(topic: str, style: str = "trivia") -> dict:
    """주제 → 검사를 통과한 대본 데이터. 결과에 사용한 프로그램(provider)도 기록."""
    base = build_prompt(topic, style)
    prompt, last_problems = base, []
    for attempt in range(1, config.load()["script"]["max_attempts"] + 1):
        text, provider = llm.generate(prompt)
        try:
            data = extract_json(text)
            problems = validate(data, topic)
        except ValueError as e:
            data, problems = None, [f"JSON 형식 오류: {e}"]
        if not problems:
            data["script"] = data["script"].strip()
            data.update(topic=topic, style=style, provider=provider, attempts=attempt)
            return review(data) if config.load()["script"].get("review", True) else data
        log.warning("대본 검사 실패 (시도 %d): %s", attempt, "; ".join(problems))
        last_problems = problems
        prev = f"\n\n# 이전 답변\n{text[:3000]}" if data else ""
        prompt = (base + prev + "\n\n# 이전 답변의 문제 (반드시 고쳐서 JSON만 다시 출력)\n- "
                  + "\n- ".join(problems))
    raise RuntimeError(f"대본 생성 실패 ({topic}): " + "; ".join(last_problems))


def upload_text(data: dict) -> str:
    """업로드 정보 txt 내용 (제목, 설명, 해시태그, 사실 확인 메모)."""
    facts = "\n".join(f"- [ ] {f}" for f in data["fact_check"])
    return (f"[제목]\n{data['title']}\n\n[설명]\n{data['description']}\n\n{' '.join(data['hashtags'])}\n\n"
            f"[업로드 전 사실 확인]\n{facts}\n\n[대본]\n{data['script']}\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="주제 → 대본 JSON")
    ap.add_argument("topic")
    ap.add_argument("--style", default="trivia")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    data = generate(args.topic, args.style)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n대본 길이: {script_length(data['script'])}자 (공백 제외)")


if __name__ == "__main__":
    main()
