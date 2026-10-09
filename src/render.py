"""FFmpeg으로 배경 영상 + 음성 + 배경음악 + 자막 → 세로 mp4.

단독 실행:
    .venv/bin/python -m src.render voice.mp3 sub.ass out.mp4 --bg bg.mp4 --music "assets/music/bright/Carefree.mp3"
"""
import argparse
import subprocess
import sys
from pathlib import Path

from src import background, config


def audio_duration(audio: Path) -> float:
    return background.clip_duration(audio)


def _audio_filter(duration: float, tail: float, has_music: bool) -> str:
    """목소리 + 배경음악 섞기. 말할 때는 음악이 자동으로 작아지고(덕킹), 앞뒤는 페이드."""
    m = config.load()["music"]
    voice = f"[1:a]aresample=48000,apad=pad_dur={tail}"
    if not has_music:
        return f"{voice},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    fade_out = max(0.0, duration - m["fade_out"])
    return (
        f"{voice},asplit=2[vo][sc];"
        f"[2:a]aresample=48000,volume={m['volume']},afade=t=in:d={m['fade_in']},"
        f"afade=t=out:st={fade_out:.3f}:d={m['fade_out']}[m];"
        f"[m][sc]sidechaincompress=threshold={m['duck_threshold']}:ratio={m['duck_ratio']}"
        f":attack=20:release=400[md];"
        f"[vo][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    )


def render(audio: Path, ass: Path, out_path: Path, bg: Path | None = None,
           music: Path | None = None, tail: float = 0.6) -> Path:
    """음성 길이 + tail초 만큼의 영상을 만든다. bg가 없으면 그라데이션 배경."""
    cfg = config.load()
    vid = cfg["video"]
    duration = audio_duration(audio) + tail
    font_dir = config.path(cfg["subtitle"]["font_dir"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bg_input = ["-i", str(bg.resolve())] if bg else ["-f", "lavfi", "-i", background.gradient_source(duration)]
    music_input = ["-stream_loop", "-1", "-i", str(music.resolve())] if music else []
    # ass 필터는 경로 특수문자 처리가 까다로워서, 자막 폴더에서 파일명만으로 실행
    subprocess.run([
        config.tool("ffmpeg"), "-y", "-loglevel", "error", "-stats" if sys.stderr.isatty() else "-nostats",
        *bg_input, "-i", str(audio.resolve()), *music_input,
        "-filter_complex", f"[0:v]ass={ass.name}:fontsdir={font_dir}[v];{_audio_filter(duration, tail, bool(music))}",
        "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", vid["preset"], "-crf", str(vid["crf"]),
        "-pix_fmt", "yuv420p", "-threads", str(vid["threads"]),
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
        str(out_path.resolve()),
    ], check=True, cwd=ass.parent)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="음성 + 자막 (+ 배경, 음악) → mp4")
    ap.add_argument("audio", type=Path)
    ap.add_argument("ass", type=Path)
    ap.add_argument("out_path", type=Path)
    ap.add_argument("--bg", type=Path, help="배경 mp4 (없으면 그라데이션)")
    ap.add_argument("--music", type=Path, help="배경음악 mp3 (없으면 음악 없음)")
    args = ap.parse_args()
    print(f"영상: {render(args.audio, args.ass, args.out_path, args.bg, args.music)}")


if __name__ == "__main__":
    main()
