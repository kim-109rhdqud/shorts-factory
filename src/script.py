"""주제 → 대본·제목·설명·해시태그 (JSON) 생성 + 검사.

스타일마다 templates/<스타일>/ 에 prompt.md(대본 지침)와 style.yaml(길이·구간·화면 설정)이 있다.
대본은 항상 "구간(segments)" 목록으로 정리된다. 잡지식처럼 한 덩어리인 스타일은 구간이 하나.
검사: JSON 형식, 필수 항목, 대본 길이, 금지 주제, 배경·음악 풀 이름, (랭킹) 순위 순서. 통과 못 하면 이유를 붙여 다시 요청.

단독 실행:
    .venv/bin/python -m src.script "문어의 심장" --out output/_work/script_test.json
    .venv/bin/python -m src.script "세상에서 가장 빠른 동물" --style ranking
"""
import argparse
import json
import logging
import re
from pathlib import Path

import yaml

from src import config, llm

log = logging.getLogger("script")

BASE_KEYS = ("title", "description", "hashtags", "background_pool", "music_pool", "fact_check")


def style_config(style: str) -> dict:
    tdir = config.path(config.load()["script"]["template_dir"]) / style
    return yaml.safe_load((tdir / "style.yaml").read_text(encoding="utf-8"))


def required_keys(st: dict) -> tuple[str, ...]:
    return BASE_KEYS + (("segments",) if st.get("segmented") else ("script",)) + tuple(st.get("extra_keys", []))


# 세는 말 앞 작은 수는 고유어로 읽어야 자연스럽다 (TTS가 "7개"를 "칠 개"로 읽는 문제)
COUNTERS = "개|명|마리|살|번|시간|가지|잔|켤레|권|장|송이|채|그루|군데|달"
_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]


def native_number(n: int) -> str:
    """1~99 → 세는 말 앞 고유어 (20 → 스무, 21 → 스물한)."""
    if n == 20:
        return "스무"
    return _TENS[n // 10] + _ONES[n % 10]


def fix_counters(text: str) -> str:
    """'7개' → '일곱 개', '17살' → '열일곱 살'. 1~99만 (큰 수, 소수점, 쉼표 숫자는 그대로)."""
    def repl(m):
        n = int(m.group(1))
        return f"{native_number(n)} {m.group(2)}" if 1 <= n <= 99 else m.group(0)
    return re.sub(rf"(?<![\d.,])(\d{{1,2}})\s?({COUNTERS})(?![가-힣]*일)", repl, text)


def normalize(data: dict, st: dict) -> None:
    """스타일과 상관없이 data["segments"]와 data["script"](전체 대본 한 줄)를 갖추게 한다."""
    if st.get("segmented"):
        segs = [x for x in data.get("segments", []) if isinstance(x, dict) and str(x.get("text", "")).strip()]
        for x in segs:
            x["text"] = fix_counters(" ".join(x["text"].split()))
            x.setdefault("label", "")
        data["segments"] = segs
        data["script"] = " ".join(x["text"] for x in segs)
    else:
        data["script"] = fix_counters(" ".join(str(data.get("script", "")).split()))
        data["segments"] = [{"label": "", "text": data["script"]}] if data["script"] else []


def _pools(ch: dict | None = None) -> tuple[list[str], list[str]]:
    """(배경 풀, 음악 풀) 이름 목록. 채널 설정에 music_pools가 있으면 그 안에서만."""
    bg = yaml.safe_load(config.path("assets/backgrounds/sources.yaml").read_text(encoding="utf-8"))["pools"]
    music = list(yaml.safe_load(config.path("assets/music/sources.yaml").read_text(encoding="utf-8"))["pools"])
    if ch and ch.get("music_pools"):
        music = [m for m in music if m in ch["music_pools"]] or music
    return list(bg), music


def _banned(ch: dict | None = None) -> list[str]:
    return config.load()["script"]["banned_topics"] + list((ch or {}).get("banned_topics", []))


def build_prompt(topic: str, style: str = "trivia", ch: dict | None = None, extra: dict | None = None) -> str:
    cfg, st = config.load()["script"], style_config(style)
    bg_pools, music_pools = _pools(ch)
    template = (config.path(cfg["template_dir"]) / style / "prompt.md").read_text(encoding="utf-8")
    return template.format(
        topic=topic, min_chars=st["min_chars"], max_chars=st["max_chars"],
        banned_topics=", ".join(_banned(ch)),
        background_pools=", ".join(bg_pools), music_pools=", ".join(music_pools), **(extra or {}),
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


def _money(text: str) -> list[int]:
    """'129만 원', '1,290,000원', '250만', '8억 3천만 원' 같은 금액 → 원 단위 정수들."""
    out = []
    for m in re.finditer(r"(\d[\d,]*)\s*억(?:\s*(\d[\d,]*)\s*천)?(?:\s*(\d[\d,]*)\s*만)?\s*원?"
                         r"|(\d[\d,]*)\s*만\s*(\d[\d,]*)?\s*원?|(\d{1,3}(?:,\d{3})+|\d{5,})\s*원", text):
        g = [x.replace(",", "") if x else None for x in m.groups()]
        if g[0]:
            v = int(g[0]) * 10 ** 8 + (int(g[1]) * 10 ** 7 if g[1] else 0) + (int(g[2]) * 10 ** 4 if g[2] else 0)
        elif g[3]:
            v = int(g[3]) * 10 ** 4 + (int(g[4]) if g[4] else 0)
        else:
            v = int(g[5])
        out.append(v)
    return out


def money_problems(data: dict, source: str) -> list[str]:
    """대본에 나온 금액이 판결문 어디에도 없으면 지어낸 것으로 본다 (2% 오차 허용).
    (1심·2심 금액을 합친 경우처럼 주문에 그대로 없는 정당한 금액도 있어서, 원문 전체와 비교 + 합계 허용)"""
    found = _money(source)
    if not found:
        return []
    sums = {a + b for a in found for b in found}
    allowed = list(set(found) | sums)
    bad = []
    for seg in data.get("segments", []):
        for v in _money(str(seg.get("item", "")) + " " + seg.get("text", "")):
            if v >= 10000 and not any(abs(v - a) <= max(a * 0.03, 10000) for a in allowed):
                bad.append(f"{v:,}원")
    return [f"판결문에 없는 금액: {', '.join(dict.fromkeys(bad))} → 판결문 금액으로"] if bad else []


def validate(data: dict, topic: str, st: dict, ch: dict | None = None, source: str = "") -> list[str]:
    """문제 목록 (비어 있으면 통과). data는 normalize 된다."""
    bg_pools, music_pools = _pools(ch)
    problems = [f"'{k}' 항목 없음" for k in required_keys(st) if k not in data]
    if problems:
        return problems
    normalize(data, st)
    script = data["script"]
    if not script:
        return ["금지 주제로 판단되어 대본이 비어 있음"]
    n = script_length(script)
    if not st["min_chars"] <= n <= st["max_chars"]:
        problems.append(f"대본 길이 {n}자 (공백 제외 {st['min_chars']}~{st['max_chars']}자여야 함)")
    # 금지 주제는 주제·제목에서만 글자로 검사 (대본 본문은 '성인 남성' 같은 오판이 많아서 AI 검토에 맡김)
    for word in _banned(ch):
        if word in topic or word in str(data.get("title", "")):
            problems.append(f"금지 주제 단어 포함: {word}")
    if re.search(r"[()\[\]<>{}#*_~]|[\U0001F300-\U0001FAFF]", script):
        problems.append("대본에 괄호·특수기호·이모지가 있음 (TTS용이라 빼야 함)")
    counted = re.findall(r"(?<![\d.,])(\d{1,2})\s?(개|명|마리|살|번|시간|가지)", script)
    if counted:
        examples = ", ".join(n + c for n, c in counted[:3])
        problems.append(f"세는 말 앞 작은 수를 숫자로 씀 ({examples}) → '세 개'처럼 한글로")
    if script.startswith(("안녕하세요", "오늘은", "여러분")):
        problems.append("첫 문장이 인사·소개로 시작함 (바로 훅으로 시작해야 함)")
    if source:
        problems += money_problems(data, source)
    if st.get("labels"):
        labeled = [x for x in data["segments"] if x.get("label")]
        if [x["label"] for x in labeled] != st["labels"]:
            problems.append(f"순위 구간은 {st['labels']} 순서여야 함")
        if any(not str(x.get("item", "")).strip() for x in labeled):
            problems.append("순위 구간마다 item(항목 이름)이 있어야 함")
    if st.get("voices") and data.get("narrator") not in st["voices"]:
        problems.append(f"narrator는 {list(st['voices'])} 중 하나여야 함")
    if "header" in st.get("extra_keys", []) and not 4 <= len(str(data.get("header", ""))) <= 32:
        problems.append("header(화면 위 사연 제목)는 4~32자여야 함")
    if data["background_pool"] not in bg_pools:
        problems.append(f"background_pool은 {bg_pools} 중 하나여야 함")
    if data["music_pool"] not in music_pools:
        problems.append(f"music_pool은 {music_pools} 중 하나여야 함")
    if not isinstance(data["hashtags"], list) or not isinstance(data["fact_check"], list):
        problems.append("hashtags와 fact_check는 목록이어야 함")
    return problems


def _first_sentence(text: str) -> str:
    return re.sub(r"\s+", "", re.split(r"(?<=[.?!])\s", text.strip(), maxsplit=1)[0])


def review(data: dict, ch: dict | None = None) -> dict:
    """두 번째 호출: 사실 오류·과장·상투적 표현을 고친다. 고친 결과가 검사에 떨어지면 원래 것을 쓴다."""
    cfg, st = config.load()["script"], style_config(data["style"])
    bg_pools, music_pools = _pools(ch)
    draft = {k: data[k] for k in required_keys(st)}
    template = (config.path(cfg["template_dir"]) / "_review.md").read_text(encoding="utf-8")
    prompt = template.format(
        draft=json.dumps(draft, ensure_ascii=False, indent=1), min_chars=st["min_chars"],
        max_chars=st["max_chars"], background_pools=", ".join(bg_pools), music_pools=", ".join(music_pools),
        keys=", ".join(required_keys(st)), style_notes=st.get("review_notes", "- (없음)"),
    )
    if data.get("source_text"):  # 판례 등 원자료가 있으면 사실 기준으로 같이 준다
        prompt += f"\n\n# 원자료 (사실은 반드시 이것과 일치해야 함)\n{data['source_text'][:6000]}"
    try:
        text, provider = llm.generate(prompt, st.get("agy_model"))
        fixed = extract_json(text)
        problems = validate(fixed, data["topic"], st, ch, data.get("source_text", ""))
        # 사실·금액 같은 중요한 문제가 없고, 다듬기 문제가 원래보다 늘지 않았으면 검토 결과를 쓴다
        before = [x for x in validate(dict(data), data["topic"], st, ch, data.get("source_text", ""))]
        if problems and all(_is_soft(x, st) for x in problems) and len(problems) <= len(before):
            fixed["warnings"] = problems
            problems = []
    except (ValueError, llm.LLMError) as e:
        problems = [str(e)]
    if not problems and _first_sentence(fixed.get("script", "")) != _first_sentence(data["script"]):
        problems = ["검토가 첫 문장(훅)을 바꿈"]  # 훅은 검토에서 손대지 못하게
    if problems:
        log.warning("검토 결과 사용 안 함 (원래 대본 유지): %s", "; ".join(problems))
        return data
    keep = required_keys(st) + ("script", "segments") + (("warnings",) if "warnings" in fixed else ())
    return {**data, **{k: fixed[k] for k in keep}, "reviewed_by": provider, "draft_script": data["script"]}


# 다듬기 문제: 마지막 시도까지 남아 있으면 경고만 남기고 통과 (사실·금액·형식 문제는 끝까지 실패)
SOFT_PROBLEMS = ("세는 말 앞 작은 수",)


def _is_soft(problem: str, st: dict) -> bool:
    if problem.startswith(SOFT_PROBLEMS):
        return True
    m = re.match(r"대본 길이 (\d+)자", problem)  # 글자 수 문제는 다듬기 (너무 짧은 것만 빼고)
    return bool(m) and int(m.group(1)) >= st["min_chars"] * 0.7


def generate(topic: str, style: str = "trivia", ch: dict | None = None, source: dict | None = None) -> dict:
    """주제 → 검사를 통과한 대본 데이터. 결과에 사용한 프로그램(provider)도 기록.
    source: 원자료 (판례 썰의 판결문 등). {"text": 원문, "info": 설명란 안내 문구에 넣을 값들}"""
    extra = {"source_text": source["text"]} if source else None
    base, st = build_prompt(topic, style, ch, extra), style_config(style)
    prompt, last_problems = base, []
    for attempt in range(1, config.load()["script"]["max_attempts"] + 1):
        text, provider = llm.generate(prompt, st.get("agy_model"))
        try:
            data = extract_json(text)
            problems = validate(data, topic, st, ch, source["text"] if source else "")
        except ValueError as e:
            data, problems = None, [f"JSON 형식 오류: {e}"]
        last = attempt == config.load()["script"]["max_attempts"]
        if problems and data and last and all(_is_soft(x, st) for x in problems):
            log.warning("다듬기 문제만 남아 통과: %s", "; ".join(problems))
            data["warnings"] = problems
            problems = []
        if not problems:
            data.update(topic=topic, style=style, provider=provider, attempts=attempt)
            if source:
                data.update(source_text=source["text"], source_info=source.get("info", {}))
            do_review = st.get("review", config.load()["script"].get("review", True))
            data = review(data, ch) if do_review else data
            if st.get("polish") and source and source.get("facts"):  # 다른 AI(Sonnet)로 다듬기
                from src import polish
                data = polish.polish(data, source["facts"], source["text"], st["polish"])
            return data
        log.warning("대본 검사 실패 (시도 %d): %s", attempt, "; ".join(problems))
        last_problems = problems
        prev = f"\n\n# 이전 답변\n{text[:3000]}" if data else ""
        prompt = (base + prev + "\n\n# 이전 답변의 문제 (반드시 고쳐서 JSON만 다시 출력)\n- "
                  + "\n- ".join(problems))
    raise RuntimeError(f"대본 생성 실패 ({topic}): " + "; ".join(last_problems))


def upload_text(data: dict) -> str:
    """업로드 정보 txt 내용 (제목, 설명, 해시태그, 사실 확인 메모)."""
    facts = "\n".join(f"- [ ] {f}" for f in data["fact_check"])
    if data["segments"] and any(x.get("label") for x in data["segments"]):
        body = "\n".join(f"[{x['label']} {x.get('item', '')}] {x['text']}" if x.get("label") else x["text"]
                         for x in data["segments"])
    else:
        body = data["script"]
    desc = data["description"]
    disclaimer = style_config(data["style"]).get("disclaimer")
    if disclaimer:
        desc += "\n" + disclaimer.format(**data.get("source_info", {}))
    screen = f"[화면 위 제목]\n{data['header']}\n\n" if data.get("header") else ""
    return (f"[제목]\n{data['title']}\n\n{screen}[설명]\n{desc}\n\n{' '.join(data['hashtags'])}\n\n"
            f"[업로드 전 사실 확인]\n{facts}\n\n[대본]\n{body}\n")


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
