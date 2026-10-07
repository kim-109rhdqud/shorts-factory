"""판례 썰 소재: 국가법령정보센터 Open API로 생활 분쟁 판례를 찾고 고른다.

법원 판결문은 저작권법 제7조에 따라 보호받지 않는 저작물이라 자유롭게 쓸 수 있다.
판결문은 이미 당사자 이름이 가려져 있다 (원고 1, 피고 등).

- 생활 키워드(templates/case/style.yaml의 keywords)로 판결문 본문 검색
- 민사 사건 중 아직 안 쓴 것 몇 개를 AI에게 보여 주고 "공감되는 생활 분쟁"을 하나 고르게 함
- 쓴 판례는 data/used_cases.json에 기록해 다시 쓰지 않음

단독 실행:
    .venv/bin/python -m src.cases search 층간소음
    .venv/bin/python -m src.cases pick
"""
import argparse
import json
import logging
import random
import re
import urllib.parse
import urllib.request

from src import config, llm, script

log = logging.getLogger("cases")

API = "https://www.law.go.kr/DRF"
USED_FILE = config.path("data/used_cases.json")


def _oc() -> str:
    """법제처 Open API 이용자 ID. .env의 LAW_API_OC (없으면 시험용 'test')."""
    try:
        return config.secret("LAW_API_OC")
    except RuntimeError:
        return "test"


def _get(path: str, **params) -> dict:
    params = {"OC": _oc(), "type": "JSON", **params}
    req = urllib.request.Request(f"{API}/{path}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": "shorts-factory/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def search(keyword: str, limit: int = 100) -> list[dict]:
    """판결문 본문에서 키워드 검색 → 민사 사건 목록."""
    data = _get("lawSearch.do", target="prec", search=2, display=limit, query=keyword)["PrecSearch"]
    hits = data.get("prec", [])
    hits = hits if isinstance(hits, list) else [hits]
    return [h for h in hits if h.get("사건종류명") == "민사" and h.get("데이터출처명", "대법원") == "대법원"]


def _clean(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def fetch(case_id: str) -> dict | None:
    """판례 상세. 주요 항목만 정리해서 돌려준다. 상세가 없는 판례는 None."""
    try:
        d = _get("lawService.do", target="prec", ID=case_id).get("PrecService")
    except Exception as e:
        log.warning("판례 %s 상세 받기 실패: %s", case_id, e)
        return None
    if not d:
        return None
    return {
        "id": str(case_id),
        "court": d.get("법원명", ""),
        "case_no": d.get("사건번호", ""),
        "name": d.get("사건명", ""),
        "date": d.get("선고일자", ""),
        "summary": _clean(d.get("판시사항", "")),
        "gist": _clean(d.get("판결요지", "")),
        "body": _clean(d.get("판례내용", "")),
    }


def used_ids() -> set[str]:
    """이미 쓴 판례 (DB 기록 + 파일 기록)."""
    from src import db
    saved = set(json.loads(USED_FILE.read_text())) if USED_FILE.exists() else set()
    return saved | db.used_case_ids()


def mark_used(case_id: str) -> None:
    ids = used_ids() | {str(case_id)}
    USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    USED_FILE.write_text(json.dumps(sorted(ids)))


def source_text(case: dict) -> str:
    """대본 작성용 원자료 (너무 길면 앞부분만)."""
    return (f"법원: {case['court']} / 사건번호: {case['case_no']} / 사건명: {case['name']} / 선고일: {case['date']}\n"
            f"[판시사항] {case['summary']}\n[판결요지] {case['gist']}\n[판결문 본문]\n{case['body'][:7000]}")


def pick(rng: random.Random | None = None, tries: int = 8) -> dict:
    """아직 안 쓴 생활 분쟁 판례 하나를 고른다 (AI가 후보 중 가장 공감되는 것 선택)."""
    rng = rng or random.Random()
    st = script.style_config("case")
    keywords = list(st["keywords"])
    rng.shuffle(keywords)
    used = used_ids()
    for keyword in keywords[:tries]:
        hits = [h for h in search(keyword) if str(h["판례일련번호"]) not in used
                and h.get("선고일자", "0")[:4] >= str(st.get("min_year", 2005))]
        if not hits:
            continue
        rng.shuffle(hits)
        cands = [fetch(h["판례일련번호"]) for h in hits[:8]]
        cands = [c for c in cands if c and len(c["body"]) > 1500 and (c["summary"] or c["gist"])]
        if not cands:
            continue
        listing = "\n".join(f"{i}. [{c['name']}] {(c['summary'] or c['gist'])[:300]}" for i, c in enumerate(cands))
        prompt = (f"아래는 '{keyword}' 관련 민사 판례 후보다. 일반인이 '나도 겪을 수 있겠다' 싶은 생활 분쟁이고, "
                  "사연으로 풀었을 때 재밌고, 결과(누가 이겼는지, 얼마를 물어 줬는지)가 분명한 것을 하나 고른다. "
                  "회사 간 분쟁, 세금, 복잡한 법리 다툼, 범죄·폭력·성 관련, 너무 무거운 사건은 피한다. "
                  "완벽하지 않아도 후보 중 가장 나은 것을 고른다. 전부 위에서 피하라고 한 종류일 때만 -1.\n\n"
                  f"{listing}\n\n숫자 하나만 출력한다.")
        text, _ = llm.generate(prompt)
        m = re.search(r"-?\d+", text)
        idx = int(m.group()) if m else -1
        if 0 <= idx < len(cands):
            log.info("판례 선택: %s %s (%s)", cands[idx]["court"], cands[idx]["case_no"], keyword)
            return {**cands[idx], "keyword": keyword}
        log.info("'%s' 후보 중 적당한 판례 없음", keyword)
    raise RuntimeError("쓸 만한 판례를 찾지 못했습니다.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="판례 검색·선택")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("keyword")
    sub.add_parser("pick")
    args = ap.parse_args()
    if args.cmd == "search":
        for h in search(args.keyword)[:20]:
            print(h["판례일련번호"], h.get("선고일자"), h["사건명"][:40])
    else:
        c = pick()
        print(f"{c['court']} {c['case_no']} {c['name']} ({c['date']})\n{c['summary'][:500]}")


if __name__ == "__main__":
    main()
