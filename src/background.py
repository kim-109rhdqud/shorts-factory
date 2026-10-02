"""배경 영상 만들기. 1단계는 천천히 움직이는 그라데이션 (진짜 배경 소스는 2단계).

단독 실행:
    .venv/bin/python -m src.background 10 output/_work/bg_test.mp4
"""
import argparse
import subprocess
from pathlib import Path

from src import config


def gradient_source(duration: float) -> str:
    """FFmpeg 입력용 그라데이션 소스 문자열 (lavfi)."""
    cfg = config.load()
    vid, colors = cfg["video"], cfg["background"]["colors"]
    cs = ":".join(f"c{i}={c}" for i, c in enumerate(colors))
    return (f"gradients=s={vid['width']}x{vid['height']}:r={vid['fps']}:{cs}"
            f":nb_colors={len(colors)}:speed=0.008:d={duration:.3f}")


def make_background(duration: float, out_path: Path) -> Path:
    """배경만 따로 mp4로 저장 (확인용)."""
    vid = config.load()["video"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        config.tool("ffmpeg"), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", gradient_source(duration),
        "-c:v", "libx264", "-preset", vid["preset"], "-crf", str(vid["crf"]),
        "-pix_fmt", "yuv420p", "-threads", str(vid["threads"]), str(out_path),
    ], check=True)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="그라데이션 배경 mp4 만들기")
    ap.add_argument("duration", type=float)
    ap.add_argument("out_path", type=Path)
    args = ap.parse_args()
    print(f"배경: {make_background(args.duration, args.out_path)}")


if __name__ == "__main__":
    main()
