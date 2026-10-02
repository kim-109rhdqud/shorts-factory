"""대본 txt 하나 → 완성 영상.

실행:
    .venv/bin/python -m src.make_video samples/sample_01.txt --channel test
    .venv/bin/python -m src.make_video samples/sample_01.txt --bg-pool ocean --music-pool mystery
"""
import argparse
import datetime as dt
import random
import shutil
from pathlib import Path

from src import background, config, export, music, render, subtitle, tts


def make(script: Path, channel: str, bg_pool: str | None = None, music_pool: str | None = None,
         upload: bool = True, keep_work: bool = False, seed: int | None = None) -> Path:
    cfg = config.load()
    bg_pool = bg_pool or cfg["background"]["pool"]
    music_pool = music_pool or cfg["music"]["pool"]
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    work = config.path(cfg["paths"]["work"]) / f"{channel}_{stamp}"
    rng = random.Random(seed)

    print("1/5 음성 만드는 중...")
    mp3, words = tts.synthesize(script.read_text(encoding="utf-8"), work)
    print("2/5 자막 만드는 중...")
    ass = subtitle.make_subtitle(words, work / "sub.ass")
    print(f"3/5 배경 만드는 중... (풀: {bg_pool})")
    duration = render.audio_duration(mp3) + 1.0
    bg = background.make_background(duration, work / "bg.mp4", bg_pool, seed=rng.randrange(1 << 30))
    track = music.pick(music_pool, rng)
    print(f"4/5 영상 합성 중... (음악: {track.stem if track else '없음'})")
    video = render.render(mp3, ass, work / "video.mp4", bg=bg, music=track)

    print("5/5 저장 중...")
    upload_text = music.credit(track) + "\n" if track else ""
    final = export.save(video, channel, upload_text)
    if not keep_work:
        shutil.rmtree(work)
    print(f"완성: {final}")
    if upload:
        print(f"드라이브: {export.upload(final.parent)}")
    return final


def main():
    ap = argparse.ArgumentParser(description="대본 txt → 완성 영상")
    ap.add_argument("script", type=Path)
    ap.add_argument("--channel", default="test")
    ap.add_argument("--bg-pool", help="배경 풀 (assets/backgrounds 아래 폴더)")
    ap.add_argument("--music-pool", help="음악 풀 (assets/music 아래 폴더)")
    ap.add_argument("--seed", type=int, help="같은 값이면 같은 배경·음악 선택")
    ap.add_argument("--no-upload", action="store_true", help="드라이브 업로드 안 함")
    ap.add_argument("--keep-work", action="store_true", help="중간 파일(음성·자막·배경) 남기기")
    args = ap.parse_args()
    make(args.script, args.channel, args.bg_pool, args.music_pool,
         upload=not args.no_upload, keep_work=args.keep_work, seed=args.seed)


if __name__ == "__main__":
    main()
