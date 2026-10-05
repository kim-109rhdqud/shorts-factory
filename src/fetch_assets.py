"""배경음악·배경 영상 등 무료 소스 내려받기.

실행:
    .venv/bin/python -m src.fetch_assets music
    .venv/bin/python -m src.fetch_assets backgrounds            # sources.yaml의 모든 풀
    .venv/bin/python -m src.fetch_assets backgrounds --pool ocean
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from src import config

MUSIC_DIR = config.path("assets/music")
BG_DIR = config.path("assets/backgrounds")
PIXABAY_VIDEO_API = "https://pixabay.com/api/videos/"


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "shorts-factory/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def music_sources() -> dict:
    return yaml.safe_load((MUSIC_DIR / "sources.yaml").read_text(encoding="utf-8"))


def fetch_music() -> None:
    src = music_sources()
    for pool, titles in src["pools"].items():
        folder = MUSIC_DIR / pool
        folder.mkdir(parents=True, exist_ok=True)
        for title in titles:
            dest = folder / f"{title}.mp3"
            if dest.exists():
                continue
            print(f"받는 중: {pool}/{title}")
            _download(src["base_url"] + urllib.parse.quote(f"{title}.mp3"), dest)
    print("음악 준비 완료")


def _pixabay_search(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "key": config.secret("PIXABAY_API_KEY"), "q": query, "per_page": 200, "safesearch": "true",
    })
    req = urllib.request.Request(f"{PIXABAY_VIDEO_API}?{params}", headers={"User-Agent": "shorts-factory/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["hits"]


def _pick_rendition(hit: dict) -> dict:
    """세로 화면을 채울 만큼만 큰 파일 (너무 큰 4K는 피해서 서버 부담 줄이기)."""
    videos = [v for v in hit["videos"].values() if v.get("url")]
    vertical = videos[0]["height"] > videos[0]["width"]
    need = 1920 if vertical else 1080
    ok = [v for v in videos if v["height"] >= need]
    return min(ok, key=lambda v: v["height"]) if ok else max(videos, key=lambda v: v["height"])


def fetch_backgrounds(only_pool: str | None = None) -> None:
    src = yaml.safe_load((BG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    per_pool = src["clips_per_pool"]
    for pool, queries in src["pools"].items():
        if only_pool and pool != only_pool:
            continue
        folder = BG_DIR / pool
        folder.mkdir(parents=True, exist_ok=True)
        meta_file = folder / "_meta.json"
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        if len(meta) >= per_pool:
            print(f"{pool}: 이미 {len(meta)}개 있음")
            continue

        # 검색어별 결과를 모아서, 세로 영상 먼저 → 가로 영상 순으로 (검색어를 번갈아 섞어 다양하게)
        results = [[h for h in _pixabay_search(q) if 5 <= h["duration"] <= 60] for q in queries]
        vertical = [h for rs in results for h in rs if _pick_rendition(h)["height"] > _pick_rendition(h)["width"]]
        mixed = [h for group in zip(*results) for h in group]
        candidates, seen = [], set(meta)
        for h in vertical + mixed:
            if str(h["id"]) not in seen:
                candidates.append(h)
                seen.add(str(h["id"]))

        for h in candidates[: per_pool - len(meta)]:
            r = _pick_rendition(h)
            dest = folder / f"pixabay_{h['id']}.mp4"
            print(f"받는 중: {pool}/{dest.name} ({r['width']}x{r['height']}, {h['duration']}초)")
            _download(r["url"], dest)
            meta[str(h["id"])] = {"file": dest.name, "page": h["pageURL"], "user": h["user"],
                                  "tags": h["tags"], "license": "Pixabay Content License"}
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        print(f"{pool}: {len(meta)}개 준비 완료")


# 검색어에서 "무엇"이 아닌 "어떻게"에 해당하는 말 (태그 일치 판단에서 뺌)
GENERIC_WORDS = {"running", "run", "flying", "fly", "swimming", "swim", "diving", "dive", "fast", "speed", "slow",
                 "motion", "close", "up", "closeup", "wild", "animal", "animals", "video", "the", "a", "an", "in",
                 "on", "of", "and", "with", "at", "view", "aerial", "shot", "footage", "beautiful", "big", "small"}


def _subject_words(query: str) -> list[str]:
    import re
    return [w for w in re.findall(r"[a-z]+", query.lower()) if w not in GENERIC_WORDS]


def _tag_score(hit: dict, required: list[str]) -> float:
    """required 단어가 태그에 전부 있으면 점수 > 0 (세로·실사 영상 가산). 하나라도 없으면 0."""
    import re
    tag_words = set(re.findall(r"[a-z]+", hit["tags"].lower()))
    if not all(w in tag_words for w in required):
        return 0.0
    r = _pick_rendition(hit)
    score = 1.0
    score += 0.5 if r["height"] > r["width"] else 0      # 세로 영상이면 조금 더
    score -= 0.6 if "generated ai" in hit["tags"] else 0  # AI 생성 영상은 덜
    return score


def search_clip(query: str, rng=None) -> Path | None:
    """검색어에 맞는 배경 영상 하나 (assets/backgrounds/_search/<검색어>/ 에 저장해 두고 재사용).
    태그에 핵심 단어가 있는 영상만 고른다 (세로 우선). 못 찾으면 None → 풀 영상으로 대신."""
    import random
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40]
    subject = _subject_words(query)
    if not slug or not subject:
        return None
    folder = BG_DIR / "_search" / slug
    cached = sorted(folder.glob("*.mp4"))
    if cached:
        return (rng or random).choice(cached)

    # 1) 핵심 단어가 태그에 전부 있는 영상 (전체 검색어 → 핵심 단어만으로 검색)
    # 2) 없으면 마지막 명사만 (영어는 끝 단어가 핵심: swift "bird", peregrine "falcon")
    attempts = [(query, subject), (" ".join(subject), subject), (subject[-1], subject[-1:])]
    best = None
    for q, required in dict.fromkeys((q, tuple(r)) for q, r in attempts):
        try:
            hits = [h for h in _pixabay_search(q) if 4 <= h["duration"] <= 60]
        except Exception as e:  # 검색 실패는 치명적이지 않음 → 풀 영상으로 대신
            print(f"검색 실패 ({q}): {e}")
            return None
        scored = sorted(((_tag_score(h, list(required)), h) for h in hits), key=lambda x: -x[0])
        if scored and scored[0][0] > 0:
            best = scored[0][1]
            break
    if best is None:
        return None
    r = _pick_rendition(best)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"pixabay_{best['id']}.mp4"
    _download(r["url"], dest)
    (folder / "_meta.json").write_text(json.dumps({"query": query, "page": best["pageURL"], "user": best["user"],
                                                   "tags": best["tags"], "license": "Pixabay Content License"},
                                                  ensure_ascii=False))
    return dest


def main():
    ap = argparse.ArgumentParser(description="무료 소스 내려받기")
    ap.add_argument("kind", choices=["music", "backgrounds"])
    ap.add_argument("--pool", help="배경 풀 하나만")
    args = ap.parse_args()
    if args.kind == "music":
        fetch_music()
    else:
        fetch_backgrounds(args.pool)


if __name__ == "__main__":
    main()
