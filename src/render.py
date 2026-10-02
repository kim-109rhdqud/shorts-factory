"""FFmpeg으로 배경 + 음성 + 자막 → 세로 mp4.

단독 실행:
    .venv/bin/python -m src.render output/_work/tts_test/voice.mp3 output/_work/tts_test/sub.ass output/_work/tts_test/out.mp4
"""
import argparse
import subprocess
from pathlib import Path

from src import background, config


def audio_duration(audio: Path) -> float:
    out = subprocess.run(
        [config.tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(audio)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def render(audio: Path, ass: Path, out_path: Path, tail: float = 0.5) -> Path:
    """음성 길이 + tail초 만큼의 영상을 만든다."""
    cfg = config.load()
    vid = cfg["video"]
    duration = audio_duration(audio) + tail
    font_dir = config.path(cfg["subtitle"]["font_dir"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ass 필터는 경로 특수문자 처리가 까다로워서, 자막 폴더에서 파일명만으로 실행
    subprocess.run([
        config.tool("ffmpeg"), "-y", "-loglevel", "error", "-stats",
        "-f", "lavfi", "-i", background.gradient_source(duration),
        "-i", str(audio.resolve()),
        "-vf", f"ass={ass.name}:fontsdir={font_dir}",
        "-map", "0:v", "-map", "1:a", "-af", f"apad=pad_dur={tail}", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", vid["preset"], "-crf", str(vid["crf"]),
        "-pix_fmt", "yuv420p", "-threads", str(vid["threads"]),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(out_path.resolve()),
    ], check=True, cwd=ass.parent)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="음성 + 자막 → mp4")
    ap.add_argument("audio", type=Path)
    ap.add_argument("ass", type=Path)
    ap.add_argument("out_path", type=Path)
    args = ap.parse_args()
    print(f"영상: {render(args.audio, args.ass, args.out_path)}")


if __name__ == "__main__":
    main()
