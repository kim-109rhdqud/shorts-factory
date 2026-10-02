"""대본 txt 하나 → 완성 영상 (1단계 파이프라인).

실행:
    .venv/bin/python -m src.make_video samples/sample_01.txt --channel test
"""
import argparse
import datetime as dt
import shutil
from pathlib import Path

from src import config, export, render, subtitle, tts


def make(script: Path, channel: str, upload: bool = True, keep_work: bool = False) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    work = config.path(config.load()["paths"]["work"]) / f"{channel}_{stamp}"

    print("1/4 음성 만드는 중...")
    mp3, words = tts.synthesize(script.read_text(encoding="utf-8"), work)
    print("2/4 자막 만드는 중...")
    ass = subtitle.make_subtitle(words, work / "sub.ass")
    print("3/4 영상 합성 중...")
    video = render.render(mp3, ass, work / "video.mp4")
    print("4/4 저장 중...")
    final = export.save(video, channel)
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
    ap.add_argument("--no-upload", action="store_true", help="드라이브 업로드 안 함")
    ap.add_argument("--keep-work", action="store_true", help="중간 파일(음성·자막) 남기기")
    args = ap.parse_args()
    make(args.script, args.channel, upload=not args.no_upload, keep_work=args.keep_work)


if __name__ == "__main__":
    main()
