"""배경 영상 만들기.

배경 풀 폴더(assets/backgrounds/<풀>)의 클립들을 무작위로 골라 세로(9:16)로 자르고
몇 초씩 이어 붙여 필요한 길이의 배경 mp4를 만든다. 풀이 비어 있으면 그라데이션으로 대신한다.
(나중에 AI 영상 등 다른 소스를 쓰려면 이 모듈만 바꾸면 된다)

단독 실행:
    .venv/bin/python -m src.background 20 output/_work/bg_test.mp4 --pool nature
"""
import argparse
import random
import subprocess
import tempfile
from pathlib import Path

from src import config

VIDEO_EXT = (".mp4", ".mov", ".webm")


def _ffmpeg_out_args() -> list[str]:
    """배경은 마지막에 한 번 더 인코딩되는 중간 파일이라, 빠른 설정 + 높은 화질로."""
    vid = config.load()["video"]
    return ["-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-threads", str(vid["threads"])]


def gradient_source(duration: float) -> str:
    """FFmpeg 입력용 그라데이션 소스 문자열 (lavfi)."""
    cfg = config.load()
    vid, colors = cfg["video"], cfg["background"]["colors"]
    cs = ":".join(f"c{i}={c}" for i, c in enumerate(colors))
    return (f"gradients=s={vid['width']}x{vid['height']}:r={vid['fps']}:{cs}"
            f":nb_colors={len(colors)}:speed=0.008:d={duration:.3f}")


def clip_duration(path: Path) -> float:
    out = subprocess.run([config.tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def list_clips(pool: str) -> list[Path]:
    folder = config.path(config.load()["background"]["dir"]) / pool
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in VIDEO_EXT)


def plan_segments(clips: list[Path], duration: float, rng: random.Random) -> list[tuple[Path, float, float]]:
    """(클립, 시작초, 길이) 목록. 같은 클립이 연달아 나오지 않게, 클립 안의 시작 위치도 무작위."""
    seg_min, seg_max = config.load()["background"]["segment_sec"]
    segments, total, last = [], 0.0, None
    while total < duration:
        choices = [c for c in clips if c != last] or clips
        clip = rng.choice(choices)
        length = min(rng.uniform(seg_min, seg_max), duration - total)
        if length < 1.0 and segments:  # 마지막 자투리는 앞 조각에 붙임
            p, s, l = segments[-1]
            segments[-1] = (p, s, l + length)
            break
        clip_len = clip_duration(clip)
        start = rng.uniform(0, max(0.0, clip_len - length - 0.1))
        segments.append((clip, start, length))
        total += length
        last = clip
    return segments


def make_background(duration: float, out_path: Path, pool: str | None = None, seed: int | None = None) -> Path:
    """배경 mp4를 만든다. 메모리를 아끼려고 조각을 하나씩 따로 만든 뒤 이어 붙인다."""
    cfg = config.load()
    vid, bg = cfg["video"], cfg["background"]
    w, h, fps = vid["width"], vid["height"], vid["fps"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clips = list_clips(pool) if pool else []
    ffmpeg = config.tool("ffmpeg")

    if not clips:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", gradient_source(duration),
                        *_ffmpeg_out_args(), str(out_path)], check=True)
        return out_path

    rng = random.Random(seed)
    # 세로로 꽉 차게 키운 뒤 가운데를 자르고, 자막이 잘 보이게 살짝 어둡게
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps},"
          f"eq=brightness={bg['brightness']}:saturation={bg['saturation']}")
    with tempfile.TemporaryDirectory(dir=out_path.parent) as tmp:
        parts = []
        for i, (clip, start, length) in enumerate(plan_segments(clips, duration, rng)):
            part = Path(tmp) / f"part{i:03d}.mp4"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                            "-i", str(clip), "-vf", vf, *_ffmpeg_out_args(), str(part)], check=True)
            parts.append(part)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(out_path)], check=True)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="배경 mp4 만들기")
    ap.add_argument("duration", type=float)
    ap.add_argument("out_path", type=Path)
    ap.add_argument("--pool", help="assets/backgrounds 아래 폴더 이름 (없으면 그라데이션)")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    print(f"배경: {make_background(args.duration, args.out_path, args.pool, args.seed)}")


if __name__ == "__main__":
    main()
