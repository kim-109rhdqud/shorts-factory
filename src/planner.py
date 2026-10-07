"""오늘 만들 영상 계획: 채널마다 스타일과 주제를 정한다 (중복 주제 제외).

- 채널의 스타일들을 번갈아 배정 (예: 썰 채널 = story, case 하나씩)
- story·trivia·ranking: AI에게 주제 후보를 받고, 예전 주제와 글자가 비슷한 것은 탈락
- case(판례 썰): 주제 대신 판례를 영상 만들 때 자동으로 고름 (여기서는 topic=None)

단독 실행 (영상은 안 만들고 계획만 보기):
    .venv/bin/python -m src.planner
    .venv/bin/python -m src.planner --channel japhak --count 3
"""
import argparse
import json
import logging
import re

from src import channels, config, db, llm, script

log = logging.getLogger("planner")

SIMILAR = 0.65       # 이 이상 비슷하면 같은 주제로 봄 (0~1)
CANDIDATES = 10      # AI에게 받는 후보 수
RECENT_IN_PROMPT = 80


# 비교할 때 떼는 조사·어미 (긴 것부터)
JOSA = ("에서는", "에게서", "으로는", "이라는", "에서", "에게", "으로", "이랑", "하고", "처럼", "보다", "까지", "부터",
        "마다", "하는", "한다", "하다", "인", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "랑")
# 주제를 구분하는 데 의미 없는 말
STOPWORDS = {"가장", "제일", "최고", "세상", "이유", "진짜", "사실", "비밀", "놀라운", "충격", "정체", "무엇", "어떻게",
             "top", "순위", "1위", "대표", "지구", "세계", "알고", "보니", "모르는", "몰랐던", "의외", "않는", "않는다", "하는", "있는", "없는",
             # 한 글자 말 중 뜻 구분에 쓸모없는 것 (꿀·새·별 같은 한 글자 명사는 살림)
             "못", "안", "세", "두", "한", "네", "더", "잘", "왜", "것", "수", "거", "좀", "또", "그", "이", "저",
             "각", "약", "총", "제", "내", "전", "후", "중", "개", "번"}


def key_words(topic: str) -> set[str]:
    """주제의 핵심 단어들: 조사를 떼고, 한 글자 말과 의미 없는 말을 뺀다. 예) '문어의 심장은?' → {문어, 심장}"""
    words = set()
    for w in re.findall(r"[가-힣a-z0-9]+", topic.lower()):
        for j in JOSA:
            if w.endswith(j) and len(w) > len(j):
                w = w[: -len(j)]
                break
        if w and w not in STOPWORDS and not w.isdigit():
            words.add(w)
    return words


def similarity(a: str, b: str) -> float:
    """두 주제가 얼마나 같은 주제인지 (0~1): 핵심 단어가 짧은 쪽 기준으로 얼마나 겹치는지.
    핵심 단어가 하나만 겹치면 절반으로 깎는다 ('번개의 온도' vs '태양의 온도' → 다른 주제)."""
    ka, kb = key_words(a), key_words(b)
    if not ka or not kb:
        return 0.0
    shared = len(ka & kb)
    score = shared / min(len(ka), len(kb))
    return score if shared >= min(2, len(ka), len(kb)) else score * 0.5


def is_duplicate(topic: str, others: list[str]) -> str | None:
    """비슷한 예전 주제가 있으면 그 주제를, 없으면 None."""
    for o in others:
        if similarity(topic, o) >= SIMILAR:
            return o
    return None


def assign_styles(ch: dict, count: int) -> list[str]:
    """스타일 배정: 최근 7일 동안 덜 만든 스타일부터 (하루 여러 번 나눠 돌려도 번갈아 나오게).
    같으면 채널 설정에 적힌 순서대로."""
    recent = db.style_counts(ch["id"], days=7)
    counts = {s: recent.get(s, 0) for s in ch["styles"]}
    order = []
    for _ in range(count):
        style = min(ch["styles"], key=lambda s: (counts[s], ch["styles"].index(s)))
        order.append(style)
        counts[style] += 1
    return order


def suggest_topics(ch: dict, style: str, n: int) -> list[str]:
    """AI 주제 후보 → 중복 제거 → n개."""
    st = script.style_config(style)
    past = db.past_topics(ch["id"])
    template = (config.path(config.load()["script"]["template_dir"]) / "_topics.md").read_text(encoding="utf-8")
    prompt = template.format(
        channel_name=ch["name"], style_name=st["name"], n=CANDIDATES, guide=st.get("topic_guide", ""),
        recent="\n".join(f"- {t}" for t in past[:RECENT_IN_PROMPT]) or "- (아직 없음)",
        banned_topics=", ".join(config.load()["script"]["banned_topics"] + ch.get("banned_topics", [])),
    )
    text, _ = llm.generate(prompt)
    topics = script.extract_json(text).get("topics", [])
    chosen = []
    for t in topics:
        t = str(t).strip()
        dup = is_duplicate(t, past + chosen)
        if dup:
            log.info("중복 탈락: '%s' ≈ '%s'", t, dup)
            continue
        chosen.append(t)
        if len(chosen) == n:
            break
    if len(chosen) < n:
        log.warning("%s: 새 주제가 %d개뿐 (필요 %d개)", ch["id"], len(chosen), n)
    return chosen


def plan_channel(channel_id: str, count: int | None = None) -> list[dict]:
    """[{channel, style, topic}] 목록. case 스타일은 topic=None (판례 자동 선택)."""
    ch = channels.load(channel_id)
    count = ch["daily_count"] if count is None else count
    styles = assign_styles(ch, count)
    plan = []
    for style in dict.fromkeys(styles):  # 스타일마다 필요한 개수만큼 한 번에
        n = styles.count(style)
        topics = [None] * n if style == "case" else suggest_topics(ch, style, n)
        plan += [{"channel": channel_id, "style": style, "topic": t} for t in topics]
    return plan


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="오늘 만들 주제 계획 보기")
    ap.add_argument("--channel", help="채널 하나만 (없으면 전부)")
    ap.add_argument("--count", type=int, help="채널당 개수 (없으면 채널 설정 daily_count)")
    args = ap.parse_args()
    for cid in [args.channel] if args.channel else channels.list_ids():
        for item in plan_channel(cid, args.count):
            print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
