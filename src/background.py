"""배경 영상 만들기.

배경 풀 폴더(assets/backgrounds/<풀>)의 클립들을 무작위로 골라 세로(9:16)로 자르고
몇 초씩 이어 붙여 필요한 길이의 배경 mp4를 만든다. 풀이 비어 있으면 그라데이션으로 대신한다.
판례 채널은 make_from_images: AI 장면 그림(확대·이동 효과) + 사용자가 만든 Flow 장면 영상.

단독 실행:
    .venv/bin/python -m src.background 20 output/_work/bg_test.mp4 --pool nature
"""
import argparse
import random
import re
import shutil
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


def detect_black_bars(clip: Path, start: float) -> str | None:
    """원본에 들어 있는 위아래·양옆 검은 띠를 찾아 FFmpeg crop 값('w:h:x:y')으로. 없으면 None."""
    out = subprocess.run([config.tool("ffmpeg"), "-hide_banner", "-ss", f"{start:.3f}", "-t", "2", "-i", str(clip),
                          "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                         capture_output=True, text=True)
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out.stderr)
    if not found:
        return None
    w, h, x, y = map(int, found[-1])
    full_w, full_h = (int(v) for v in subprocess.run(
        [config.tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(clip)], capture_output=True, text=True, check=True).stdout.strip().split(","))
    # 화면이 거의 그대로면(띠 없음) 또는 너무 많이 잘리면(어두운 장면 오판) 자르지 않음
    if w * h >= full_w * full_h * 0.97 or w * h < full_w * full_h * 0.5:
        return None
    return f"{w}:{h}:{x}:{y}"


def _render_part(clip: Path, start: float, length: float, part: Path, vf: str) -> None:
    """클립의 start부터 length초를 세로로 잘라 저장. 클립이 짧으면 반복 재생. 검은 띠는 먼저 잘라냄."""
    loop = ["-stream_loop", "-1"] if clip_duration(clip) < start + length else []
    bars = detect_black_bars(clip, start)
    if bars:
        vf = f"crop={bars}," + vf
    subprocess.run([config.tool("ffmpeg"), "-y", "-loglevel", "error", *loop, "-ss", f"{start:.3f}",
                    "-t", f"{length:.3f}", "-i", str(clip), "-vf", vf, *_ffmpeg_out_args(), str(part)], check=True)


def plan_by_segments(segments: list[dict], duration: float, clips: list[Path],
                     rng: random.Random) -> list[tuple[Path, float, float]]:
    """구간마다 배경 하나: bg_query로 검색한 영상 → 없으면 풀에서 (직전과 다른 것)."""
    from src.fetch_assets import search_clip

    plan, last = [], None
    for i, seg in enumerate(segments):
        start = 0.0 if i == 0 else seg["start"]
        end = segments[i + 1]["start"] if i + 1 < len(segments) else duration
        length = end - start
        clip = search_clip(seg["bg_query"], rng) if seg.get("bg_query") else None
        if clip is None:
            if not clips:
                raise RuntimeError("배경 풀이 비어 있고 검색 영상도 없습니다.")
            clip = rng.choice([c for c in clips if c != last] or clips)
        offset = rng.uniform(0, max(0.0, clip_duration(clip) - length - 0.1))
        plan.append((clip, offset, length))
        last = clip
    return plan


def make_background(duration: float, out_path: Path, pool: str | None = None, seed: int | None = None,
                    segments: list[dict] | None = None) -> Path:
    """배경 mp4를 만든다. 메모리를 아끼려고 조각을 하나씩 따로 만든 뒤 이어 붙인다.
    segments를 주면 구간마다 배경을 바꾼다 (랭킹 등)."""
    cfg = config.load()
    vid, bg = cfg["video"], cfg["background"]
    w, h, fps = vid["width"], vid["height"], vid["fps"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clips = list_clips(pool) if pool else []
    ffmpeg = config.tool("ffmpeg")

    if not clips and not segments:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", gradient_source(duration),
                        *_ffmpeg_out_args(), str(out_path)], check=True)
        return out_path

    rng = random.Random(seed)
    plan = plan_by_segments(segments, duration, clips, rng) if segments else plan_segments(clips, duration, rng)
    # 세로로 꽉 차게 키운 뒤 가운데를 자르고, 자막이 잘 보이게 살짝 어둡게
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps},"
          f"eq=brightness={bg['brightness']}:saturation={bg['saturation']}")
    with tempfile.TemporaryDirectory(dir=out_path.parent) as tmp:
        parts = []
        for i, (clip, start, length) in enumerate(plan):
            part = Path(tmp) / f"part{i:03d}.mp4"
            _render_part(clip, start, length, part, vf)
            parts.append(part)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(out_path)], check=True)
    return out_path


# ---------- AI 장면 그림 → 움직이는 배경 ----------

def _squash(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text)


def scene_starts(scenes: list[dict], script_text: str, words: list[dict], duration: float) -> list[float]:
    """장면마다 시작 시간(초). 장면의 "from"(대본 문장 앞부분)을 대본에서 찾아 그 단어가 읽히는 시간으로.
    못 찾거나 순서가 꼬이면 그 장면은 앞뒤 사이 중간쯤으로."""
    flat = _squash(script_text)
    # 단어마다 '공백 뺀 대본'에서의 시작 글자 위치
    pos, offsets = 0, []
    for w in words:
        k = flat.find(_squash(w["text"]), pos)
        offsets.append(k if k >= 0 else pos)
        pos = (k if k >= 0 else pos) + len(_squash(w["text"]))
    starts = []
    for i, sc in enumerate(scenes):
        if i == 0:
            starts.append(0.0)
            continue
        k = flat.find(_squash(sc.get("from", ""))[:10]) if sc.get("from") else -1
        t = None
        if k >= 0:
            idx = next((j for j, o in enumerate(offsets) if o >= k), len(words) - 1)
            t = words[idx]["start"]
        starts.append(t)
    # 빈 칸·순서 꼬임 보정: 앞 장면보다 2초 이상 뒤가 아니면 균등 분배로
    even = [duration * i / len(scenes) for i in range(len(scenes))]
    fixed = []
    for i, t in enumerate(starts):
        prev = fixed[-1] if fixed else -1
        fixed.append(t if t is not None and t >= prev + 2.0 and t < duration - 2.0 else max(even[i], prev + 2.0))
    return fixed


KEN_BURNS = {  # 확대·이동 효과 (p = 0→1 진행률)
    "zoom_in": ("1+0.18*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.18-0.18*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_down": ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*{p}"),
    "pan_up": ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-{p})"),
}


MAX_SLOW = 1.35  # Flow 영상을 장면 길이에 맞출 때 최대 몇 배까지 느리게 할지 (그 이상은 마지막 화면 유지)


def _clip_part(clip: Path, part_len: float, part: Path, w: int, h: int, fps: int) -> None:
    """Flow 영상 → 세로로 꽉 채워 자르고, 장면 길이에 맞게 살짝 느리게(최대 1.35배), 그래도 짧으면 마지막 화면 유지. 소리 끔."""
    d = clip_duration(clip)
    factor = min(MAX_SLOW, max(1.0, part_len / d)) if d > 0 else 1.0
    hold = max(0.0, part_len - d * factor)
    vf = (f"setpts=PTS*{factor:.4f},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
          f"fps={fps}" + (f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.05 else ""))
    subprocess.run([config.tool("ffmpeg"), "-y", "-loglevel", "error", "-i", str(clip), "-vf", vf, "-an",
                    "-t", f"{part_len:.3f}", *_ffmpeg_out_args(), str(part)], check=True)


def make_from_images(images: list[Path | None], starts: list[float], duration: float, out_path: Path,
                     seed: int | None = None, fade: float = 0.5, clips: list[Path | None] | None = None) -> Path:
    """장면 그림들을 확대·이동 효과 + 부드러운 전환(xfade)으로 이어 배경 mp4를 만든다.
    clips[i]가 있으면 그 장면은 그림 대신 Flow 영상. 못 만든 그림(None)은 앞(없으면 뒤) 그림으로 채움.
    그림·영상이 절반 이상 없으면 오류."""
    clips = (list(clips or []) + [None] * len(images))[:len(images)]
    valid = [p for p in images if p]
    if len(valid) + sum(1 for c in clips if c) < max(1, len(images) / 2):
        raise RuntimeError("장면 그림이 너무 적음")
    filled, last = [], None
    for p in images:
        last = p or last
        filled.append(last)
    filled = [p or (valid[0] if valid else None) for p in filled]  # Flow 영상 장면은 그림이 없어도 됨

    vid, bg = config.load()["video"], config.load()["background"]
    w, h, fps = vid["width"], vid["height"], vid["fps"]
    rng = random.Random(seed)
    lengths = [(starts[i + 1] if i + 1 < len(starts) else duration) - starts[i] for i in range(len(starts))]
    effects, prev = [], None
    for _ in lengths:
        prev = rng.choice([e for e in KEN_BURNS if e != prev])
        effects.append(prev)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_path.parent) as tmp:
        parts = []
        for i, (img, length, eff) in enumerate(zip(filled, lengths, effects)):
            part_len = length + (fade if i + 1 < len(lengths) else 0)
            if clips[i]:  # 이 장면은 Flow 영상
                part = Path(tmp) / f"img{i:02d}.mp4"
                _clip_part(clips[i], part_len, part, w, h, fps)
                parts.append(part)
                continue
            frames = max(2, round(part_len * fps))
            p = f"(on/{frames - 1})"
            z, x, y = (e.format(p=p) for e in KEN_BURNS[eff])
            vf = (f"scale={w * 3 // 2}:-2,zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps},"
                  f"eq=brightness={bg['brightness'] / 2}:saturation=1.05,setsar=1")
            part = Path(tmp) / f"img{i:02d}.mp4"
            subprocess.run([config.tool("ffmpeg"), "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps),
                            "-t", f"{part_len:.3f}", "-i", str(img), "-vf", vf, "-frames:v", str(frames),
                            *_ffmpeg_out_args(), str(part)], check=True)
            parts.append(part)
        if len(parts) == 1:
            shutil.copy(parts[0], out_path)
            return out_path
        inputs, chain, offset, label = [], [], 0.0, "0:v"
        for i, part in enumerate(parts):
            inputs += ["-i", str(part)]
        for i in range(1, len(parts)):
            offset += lengths[i - 1]
            out = f"v{i}"
            chain.append(f"[{label}][{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}[{out}]")
            label = out
        subprocess.run([config.tool("ffmpeg"), "-y", "-loglevel", "error", *inputs, "-filter_complex",
                        ";".join(chain), "-map", f"[{label}]", *_ffmpeg_out_args(), str(out_path)], check=True)
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
