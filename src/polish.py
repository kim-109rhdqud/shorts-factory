"""다른 AI(Antigravity의 Claude Sonnet)로 대본 다듬기. 평가자에게는 최소한의 정보만 준다.

1) 평가: "유튜브 쇼츠 대본이야. 솔직하게 평가해 줘" + 대본만 (우리 지침·기준표·판결문은 주지 않음)
2) 고쳐 쓰기: 대본 + 그 평가만 주고 "평가를 전부 반영해서 고쳐 줘"
3) 다시 평가 → 큰 문제가 남았으면 한 번 더 고쳐 쓰기 (max_rounds)
4) 사실 확인: 사실 목록과 다른 사실만 고치고 말투·구성은 그대로 (작가 AI), 판결 구간 나누기, 장면 위치 다시 찾기
5) 금액 검사(판결문에 없는 금액이면 사실 확인 다시), "7개 → 일곱 개" 자동 변환

단독 실행 (저장된 대본 JSON 다듬기):
    .venv/bin/python -m src.polish output/_work/draft.json <판례ID>
"""
import argparse
import json
import logging
import re

from src import config, llm, script

log = logging.getLogger("polish")


def _template(name: str) -> str:
    return (config.path(config.load()["script"]["template_dir"]) / name).read_text(encoding="utf-8")


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(\[?고친 대본\]?|대본)\s*[:：]?\s*", "", text.strip())
    return " ".join(text.strip("“”\"' \n").split())


def evaluate(text: str, model: str) -> str:
    out, _ = llm.generate(_template("_evaluate.md").format(script=text), agy_model=model, providers=["agy"])
    return out.strip()


def rewrite(text: str, critique: str, model: str) -> str:
    critique = re.sub(r"\[큰 문제:\s*(있음|없음)\]", "", critique).strip()
    out, _ = llm.generate(_template("_rewrite.md").format(script=text, critique=critique), agy_model=model,
                          providers=["agy"])
    return _clean(out)


def titles(text: str, model: str) -> tuple[str, str] | None:
    """완성 대본만 주고 제목과 화면 위 제목을 받는다 (최소 정보). 형식이 안 맞으면 None."""
    out, _ = llm.generate(_template("_title.md").format(script=text), agy_model=model, providers=["agy"])
    t = re.search(r"\[제목\]\s*(.+)", out)
    h = re.search(r"\[화면 제목\]\s*(.+)", out)
    if not (t and h):
        return None
    clean = lambda x: x.strip().strip("“”\"'").strip()
    return clean(t.group(1))[:40], clean(h.group(1))[:24]


META_TAIL = re.compile(r"[^.?!]*(설명란|사건번호|판결문을 확인|판결문과 함께|구독|좋아요|알림 설정|팔로우|도움이 되셨|"
                       r"자료에 없|확인한 자료|확인이 필요)[^.?!]*[.?!]")


def strip_meta(text: str) -> str:
    """'사건번호는 설명란에…', '구독과 좋아요' 같은 영상 밖 안내 문장을 뺀다."""
    return " ".join(META_TAIL.sub("", text).split())


VIEWER_TAIL = re.compile(r"(세요|주세요|마세요|보세요|드립니다|바랍니다)[.!]?$|댓글|구독|공유해|게 좋습니다|게 좋아요"
                         r"|어떻게 해야 할까요|기억하세요|잊지 마|혼자 참지|도움을 요청|미리 확인|꼭 확인")


def strip_viewer_tail(text: str) -> str:
    """끝에서부터 시청자에게 하는 당부·댓글 유도 문장을 뺀다 (사용자 결정 2026-10-09: 마무리 문장 없이)."""
    sents = [x for x in re.split(r"(?<=[.?!])\s+", text.strip()) if x]
    while sents and VIEWER_TAIL.search(sents[-1]):
        sents.pop()
    return " ".join(sents)


def _punctuated(text: str) -> bool:
    """문장부호가 충분한지 (대략 80자에 하나 이상)."""
    return len(re.findall(r"[.?!]", text)) >= max(2, len(text) // 80)


def fact_fix(text: str, facts: dict, scenes: list[dict], source: str, tries: int = 2) -> dict:
    scene_list = "\n".join(f"{i}. {s.get('image', '')}" for i, s in enumerate(scenes, 1)) or "(없음)"
    prompt = _template("case/factfix.md").format(facts=json.dumps(facts, ensure_ascii=False, indent=1),
                                                 scenes=scene_list, script=text)
    for attempt in range(tries):
        fixed = script.extract_json(llm.generate(prompt)[0])
        segs = [{"label": "", "text": script.fix_counters(strip_meta(fixed["story"]))},
                {"label": "판결", "item": fixed.get("verdict_item", ""),
                 "text": script.fix_counters(strip_viewer_tail(strip_meta(fixed["verdict"])))}]
        money = script.money_problems({"segments": segs}, source)
        if not all(_punctuated(x["text"]) for x in segs):
            log.warning("사실 확인 결과에 문장부호가 부족함, 다시")
            prompt += "\n\n# 이전 결과의 문제\n- 문장 끝 마침표가 빠졌음. 모든 문장 끝에 마침표를 붙일 것"
            continue
        if not money:
            return {"segments": segs, "changes": fixed.get("changes", []), "scene_from": fixed.get("scene_from", [])}
        log.warning("사실 확인 후에도 금액 문제: %s", money)
        prompt += "\n\n# 이전 결과의 문제 (판결문 금액으로 고칠 것)\n- " + "\n- ".join(money)
    raise RuntimeError("사실 확인 실패 (금액 또는 문장부호)")


def polish(data: dict, facts: dict, source: str, cfg: dict) -> dict:
    """초안 data → 다듬은 data (segments, script, scenes의 from, 기록 polish_log 갱신)."""
    model, rounds = cfg["model"], cfg.get("max_rounds", 2)
    text = " ".join(s["text"] for s in data["segments"])
    logs = []
    critique = evaluate(text, model)
    for r in range(rounds):
        logs.append({"round": r + 1, "critique": critique})
        text = rewrite(text, critique, model)
        logs[-1]["rewrite"] = text
        critique = evaluate(text, model)
        if "[큰 문제: 없음]" in critique:
            logs.append({"round": r + 1, "final_critique": critique})
            break
    else:
        logs.append({"final_critique": critique})
    fixed = fact_fix(text, facts, data.get("scenes", []), source)
    scenes = data.get("scenes", [])
    for sc, anchor in zip(scenes, fixed["scene_from"]):
        sc["from"] = anchor
    final_text = " ".join(x["text"] for x in fixed["segments"])
    try:  # 제목도 다른 AI가 완성 대본만 보고 짓기
        named = titles(final_text, model)
    except llm.LLMError as e:
        log.warning("제목 짓기 실패, 초안 제목 사용: %s", e)
        named = None
    if named:
        data = {**data, "title": named[0], "header": named[1], "draft_title": data.get("title")}
    out = {**data, "segments": fixed["segments"], "scenes": scenes,
           "script": " ".join(s["text"] for s in fixed["segments"]),
           "polish_log": logs, "fact_changes": fixed["changes"]}
    out["draft_script"] = " ".join(s["text"] for s in data["segments"])
    return out


def main():
    from src import cases
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="저장된 대본 JSON을 Sonnet으로 다듬기")
    ap.add_argument("draft_json")
    ap.add_argument("case_id")
    args = ap.parse_args()
    case = cases.fetch(args.case_id)
    st = script.style_config("case")
    out = polish(json.load(open(args.draft_json)), cases.fact_sheet(case), cases.writing_source(case), st["polish"])
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
