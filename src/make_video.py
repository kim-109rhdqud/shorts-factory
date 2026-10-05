"""주제 한 줄 또는 대본 txt → 완성 영상.

실행:
    .venv/bin/python -m src.make_video --topic "문어의 심장"                 # AI가 대본 작성 (잡지식)
    .venv/bin/python -m src.make_video --topic "세상에서 가장 빠른 동물" --style ranking   # 랭킹 TOP 5
    .venv/bin/python -m src.make_video --script samples/sample_01.txt      # 직접 쓴 대본
    .venv/bin/python -m src.make_video --script samples/sample_01.txt --bg-pool ocean --music-pool mystery
"""
import argparse
import datetime as dt
import logging
import random
import shutil
from pathlib import Path

from src import background, config, export, music, render, script, subtitle, tts


def make(segments: list[dict], channel: str, style: str = "trivia", bg_pool: str | None = None,
         music_pool: str | None = None, info: str = "", upload: bool = True, keep_work: bool = False,
         seed: int | None = None, voice: str | None = None, header: str | None = None) -> Path:
    """대본 구간 목록 → 완성 영상. info는 업로드 정보 txt에 넣을 내용(제목·설명 등).
    voice: 목소리 (없으면 기본), header: 화면 위에 계속 띄울 제목 (썰 등)"""
    cfg, st = config.load(), script.style_config(style)
    bg_pool = bg_pool or cfg["background"]["pool"]
    music_pool = music_pool or cfg["music"]["pool"]
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    work = config.path(cfg["paths"]["work"]) / f"{channel}_{stamp}"
    rng = random.Random(seed)

    print(f"1/5 음성 만드는 중... ({st['name']}, 구간 {len(segments)}개)")
    mp3, words, times = tts.synthesize_segments(segments, work, st.get("segment_pause", 0.3), voice=voice)
    print("2/5 자막 만드는 중...")
    ass = subtitle.make_subtitle(words, work / "sub.ass", times, st.get("layout"), header)
    print(f"3/5 배경 만드는 중... (풀: {bg_pool}{', 구간마다 전환' if st.get('background') == 'per_segment' else ''})")
    duration = render.audio_duration(mp3) + 1.0
    per_segment = times if st.get("background") == "per_segment" else None
    bg = background.make_background(duration, work / "bg.mp4", bg_pool, seed=rng.randrange(1 << 30),
                                    segments=per_segment)
    track = music.pick(music_pool, rng)
    print(f"4/5 영상 합성 중... (음악: {track.stem if track else '없음'})")
    video = render.render(mp3, ass, work / "video.mp4", bg=bg, music=track)

    print("5/5 저장 중...")
    credit = f"[음악 출처 - 설명란에 꼭 넣기]\n{music.credit(track)}\n" if track else ""
    final = export.save(video, channel, "\n".join(x for x in (info, credit) if x))
    if not keep_work:
        shutil.rmtree(work)
    print(f"완성: {final}")
    if upload:
        print(f"드라이브: {export.upload(final.parent)}")
    return final


def make_from_topic(topic: str, channel: str, style: str = "trivia", **kwargs) -> Path:
    """주제 → AI 대본 → 완성 영상. 배경·음악 풀은 AI가 고른 것을 쓰되, 직접 지정하면 그걸 우선."""
    print(f"0/5 대본 쓰는 중... (주제: {topic}, 스타일: {style})")
    data = script.generate(topic, style)
    print(f"    제목: {data['title']} ({data['provider']}, {script.script_length(data['script'])}자)")
    kwargs["bg_pool"] = kwargs.get("bg_pool") or data["background_pool"]
    kwargs["music_pool"] = kwargs.get("music_pool") or data["music_pool"]
    st = script.style_config(style)
    if st.get("voices"):
        kwargs["voice"] = st["voices"][data["narrator"]]
    return make(data["segments"], channel, style, info=script.upload_text(data), header=data.get("header"), **kwargs)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="주제 또는 대본 txt → 완성 영상")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--topic", help="주제 한 줄 (AI가 대본 작성)")
    src.add_argument("--script", type=Path, help="직접 쓴 대본 txt")
    ap.add_argument("--channel", default="test")
    ap.add_argument("--style", default="trivia", help="대본 스타일 (templates 아래 폴더)")
    ap.add_argument("--bg-pool", help="배경 풀 (assets/backgrounds 아래 폴더)")
    ap.add_argument("--music-pool", help="음악 풀 (assets/music 아래 폴더)")
    ap.add_argument("--seed", type=int, help="같은 값이면 같은 배경·음악 선택")
    ap.add_argument("--no-upload", action="store_true", help="드라이브 업로드 안 함")
    ap.add_argument("--keep-work", action="store_true", help="중간 파일(음성·자막·배경) 남기기")
    args = ap.parse_args()
    opts = dict(bg_pool=args.bg_pool, music_pool=args.music_pool, upload=not args.no_upload,
                keep_work=args.keep_work, seed=args.seed)
    if args.topic:
        make_from_topic(args.topic, args.channel, args.style, **opts)
    else:
        make([{"label": "", "text": args.script.read_text(encoding="utf-8")}], args.channel, **opts)


if __name__ == "__main__":
    main()
