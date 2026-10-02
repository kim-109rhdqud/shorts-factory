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
