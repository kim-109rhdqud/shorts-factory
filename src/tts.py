"""대본 → 음성(mp3) + 단어별 타이밍(json).

목소리 이름이 "supertonic:M1"처럼 시작하면 Supertonic(서버 안에서 직접 만드는 무료 음성, 수퍼톤 공개 모델,
OpenRAIL-M 상업 사용 가능), 아니면 edge-tts.
- edge-tts: 2026-10-10부터 마이크로소프트 접속 방식 변경으로 403 오류 → 판례 채널은 Supertonic으로 바꿈
- Supertonic은 단어 타이밍을 주지 않음 → 문장마다 따로 만들고, 문장 안에서는 글자 수 비율로 단어 시간을 나눔

구간(segments)별로 따로 만들어 이어 붙이고, 각 구간의 시작·끝 시간도 기록한다 (랭킹 순위 표시, 배경 전환용).

단독 실행:
    .venv/bin/python -m src.tts samples/sample_01.txt output/_work/tts_test
"""
import argparse
import asyncio
import json
import re
import subprocess
from pathlib import Path

import edge_tts

from src import config


async def _synthesize(text: str, voice: str, rate: str, pitch: str, mp3_path: Path) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7  # 100ns 단위 → 초
                words.append({
                    "text": chunk["text"],
                    "start": round(start, 3),
                    "end": round(start + chunk["duration"] / 1e7, 3),
                })
    return words


def _restore_punctuation(text: str, words: list[dict]) -> None:
    """edge-tts 단어에는 문장부호가 빠져 있어서, 원문에서 찾아 붙여 준다 (예: 잡니다 → 잡니다.)."""
    cursor = 0
    for w in words:
        idx = text.find(w["text"], cursor)
        if idx < 0:  # 숫자 읽기 등으로 원문과 다르면 그대로 둠
            continue
        end = idx + len(w["text"])
        while end < len(text) and not text[end].isspace():
            end += 1
        w["text"] = text[idx:end]
        cursor = end


# ---------- Supertonic (서버 안에서 직접) ----------

SUPERTONIC = "supertonic:"
SENTENCE_GAP = 0.18   # 문장 사이 쉼 (초)
_engine = None


def _supertonic():
    global _engine
    if _engine is None:  # 모델 읽는 데 약 30초 → 한 번만
        from supertonic import TTS
        _engine = TTS()
    return _engine


def _speed(rate: str | None) -> float:
    """edge-tts식 속도("+25%") → Supertonic 배속 (1.25). 0.7~2.0."""
    m = re.match(r"([+-]?\d+)%", rate or "")
    return min(2.0, max(0.7, 1 + int(m.group(1)) / 100 if m else 1.05))


def _trim(wav, sr: int, threshold: float = 0.01):
    """앞뒤 무음 잘라내기 (단어 시간을 실제 말소리에 맞추려고)."""
    import numpy as np
    loud = np.nonzero(np.abs(wav) > threshold)[0]
    if not len(loud):
        return wav
    return wav[max(0, loud[0] - int(0.02 * sr)): loud[-1] + int(0.05 * sr)]


def _supertonic_synthesize(text: str, voice: str, rate: str | None, mp3_path: Path) -> list[dict]:
    import numpy as np
    import soundfile as sf
    tts = _supertonic()
    style, speed, sr = tts.get_voice_style(voice), _speed(rate), tts.sample_rate
    sentences = [x for x in re.split(r"(?<=[.?!])\s+", text) if x.strip()]
    gap = np.zeros(int(SENTENCE_GAP * sr), dtype=np.float32)
    pieces, words, t = [], [], 0.0
    for i, sent in enumerate(sentences):
        wav, _ = tts.synthesize(sent, voice_style=style, lang="ko", speed=speed)
        wav = _trim(np.asarray(wav, dtype=np.float32).squeeze(), sr)
        dur = len(wav) / sr
        # 문장 안 단어 시간 = 글자 수 비율 (공백 뺀 글자 + 단어 사이 약간의 틈)
        ws = sent.split()
        weights = [len(re.sub(r"[^\w]", "", w)) + 0.6 for w in ws]
        total, acc = sum(weights), 0.0
        for w, wt in zip(ws, weights):
            start = t + dur * acc / total
            acc += wt
            words.append({"text": w, "start": round(start, 3), "end": round(t + dur * acc / total, 3)})
        pieces.append(wav)
        t += dur
        if i + 1 < len(sentences):
            pieces.append(gap)
            t += SENTENCE_GAP
    wav_path = mp3_path.with_suffix(".wav")
    sf.write(str(wav_path), np.concatenate(pieces), sr)
    subprocess.run([config.tool("ffmpeg"), "-y", "-loglevel", "error", "-i", str(wav_path), "-c:a", "libmp3lame",
                    "-b:a", "160k", str(mp3_path)], check=True)
    wav_path.unlink()
    return words


def synthesize(text: str, out_dir: Path, voice: str | None = None, rate: str | None = None,
               pitch: str | None = None) -> tuple[Path, Path]:
    """음성과 타이밍 파일을 out_dir에 만들고 (mp3 경로, json 경로)를 돌려준다."""
    cfg = config.load()["voice"]
    voice = voice or cfg["name"]
    rate = rate or cfg["rate"]
    pitch = pitch or "+0Hz"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / "voice.mp3"
    json_path = out_dir / "words.json"

    text = " ".join(text.split())  # 줄바꿈·연속 공백 정리
    if voice.startswith(SUPERTONIC):
        words = _supertonic_synthesize(text, voice[len(SUPERTONIC):], rate, mp3_path)
        json_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        return mp3_path, json_path
    words = asyncio.run(_synthesize(text, voice, rate, pitch, mp3_path))
    if not words:
        raise RuntimeError("edge-tts가 단어 타이밍을 주지 않았습니다.")
    _restore_punctuation(text, words)
    json_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    return mp3_path, json_path


def _duration(path: Path) -> float:
    out = subprocess.run([config.tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def synthesize_segments(segments: list[dict], out_dir: Path, pause: float = 0.3, voice: str | None = None,
                        rate: str | None = None, pitch: str | None = None) -> tuple[Path, Path, list[dict]]:
    """구간마다 음성을 만들어 pause초씩 띄워 이어 붙인다.
    돌려주는 것: (voice.mp3, words.json, 구간 시간 목록 [{label, item, bg_query, start, end}])"""
    if len(segments) == 1:
        mp3, js = synthesize(segments[0]["text"], out_dir, voice, rate, pitch)
        end = json.loads(js.read_text(encoding="utf-8"))[-1]["end"]
        return mp3, js, [dict(segments[0], start=0.0, end=end)]

    out_dir.mkdir(parents=True, exist_ok=True)
    all_words, times, inputs, offset = [], [], [], 0.0
    for i, seg in enumerate(segments):
        part = out_dir / f"seg{i:02d}"
        mp3, js = synthesize(seg["text"], part, voice, rate, pitch)
        dur = _duration(mp3)
        for w in json.loads(js.read_text(encoding="utf-8")):
            all_words.append({**w, "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)})
        times.append(dict(seg, start=round(offset, 3), end=round(offset + dur, 3)))
        inputs.append(mp3)
        offset += dur + pause

    # 구간 사이에 pause초 무음을 넣어 이어 붙임 (마지막 구간 뒤에는 무음 없음)
    n = len(inputs)
    pads = "".join(f"[{i}:a]aresample=24000,apad=pad_dur={pause if i < n - 1 else 0}[a{i}];" for i in range(n))
    concat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    mp3_path, json_path = out_dir / "voice.mp3", out_dir / "words.json"
    cmd = [config.tool("ffmpeg"), "-y", "-loglevel", "error"]
    for f in inputs:
        cmd += ["-i", str(f)]
    subprocess.run(cmd + ["-filter_complex", pads + concat, "-map", "[out]", "-c:a", "libmp3lame",
                          "-b:a", "160k", str(mp3_path)], check=True)
    json_path.write_text(json.dumps(all_words, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "segments.json").write_text(json.dumps(times, ensure_ascii=False, indent=1), encoding="utf-8")
    return mp3_path, json_path, times


def main():
    ap = argparse.ArgumentParser(description="대본 txt → 음성 mp3 + 단어 타이밍 json")
    ap.add_argument("script", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--voice")
    ap.add_argument("--rate")
    args = ap.parse_args()
    mp3, js = synthesize(args.script.read_text(encoding="utf-8"), args.out_dir, args.voice, args.rate)
    words = json.loads(js.read_text(encoding="utf-8"))
    print(f"음성: {mp3}\n타이밍: {js} ({len(words)}단어, {words[-1]['end']:.1f}초)")


if __name__ == "__main__":
    main()
