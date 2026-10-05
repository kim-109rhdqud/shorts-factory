"""단어 타이밍(json) → 쇼츠식 자막(.ass).

단독 실행:
    .venv/bin/python -m src.subtitle output/_work/tts_test/words.json output/_work/tts_test/sub.ass
"""
import argparse
import json
from pathlib import Path

from src import config

SENTENCE_END = (".", "?", "!", "…")
# 앞말에 붙어야 자연스러운 말 (의존명사 등). 이 말로 시작하는 위치에서는 가급적 안 끊는다.
BOUND_STARTS = ("것", "걸", "건", "게", "거", "수", "때", "데", "줄", "적", "뿐", "만큼", "듯", "중", "동안", "개", "번", "명", "살", "년")
# 뒷말과 붙어야 자연스러운 한 글자 말 (수·꾸밈말). 이 말 뒤에서는 가급적 안 끊는다.
BOUND_ENDS = {"몇", "한", "두", "세", "네", "더", "잘", "못", "안", "꼭", "좀", "또", "새", "이", "그", "저", "각", "약", "총"}


def _text(ws: list[dict]) -> str:
    return " ".join(w["text"] for w in ws)


def _split_phrases(words: list[dict], pause_split: float) -> list[list[dict]]:
    """문장부호(.,?!)나 말 쉬는 곳에서 크게 나눈다."""
    phrases, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["text"].endswith(SENTENCE_END + (",",)) or nxt["start"] - w["end"] >= pause_split:
            phrases.append(cur)
            cur = []
    return phrases


def _balanced_split(ws: list[dict], max_chars: int, max_words: int) -> list[list[dict]]:
    """긴 구절을 되도록 적은 개수로, 길이가 고르게, 어색한 곳은 피해서 나눈다.
    모든 나누는 방법 중 점수가 가장 낮은 것을 고른다 (동적 계획법)."""
    n = len(ws)
    best = [0.0] + [float("inf")] * n  # best[i]: 앞의 i단어를 나눈 최소 점수
    prev = [0] * (n + 1)
    for i in range(1, n + 1):
        for j in range(i - 1, -1, -1):  # 마지막 덩어리 = ws[j:i]
            seg = ws[j:i]
            length = len(_text(seg))
            if (length > max_chars or len(seg) > max_words) and len(seg) > 1:
                break
            score = best[j] + 30 + (length - max_chars * 0.7) ** 2 / 4  # 덩어리 수 적게, 길이 고르게
            if len(seg) == 1 and length <= 2:
                score += 40  # '해요', '기어' 처럼 짧은 말 하나만 뜨는 것 방지
            if j > 0 and (seg[0]["text"].startswith(BOUND_STARTS) or ws[j - 1]["text"] in BOUND_ENDS):
                score += 100  # '몇 / 개일까요', '걸 / 더' 같은 끊김 방지
            if score < best[i]:
                best[i], prev[i] = score, j
    parts, i = [], n
    while i > 0:
        parts.append(ws[prev[i]:i])
        i = prev[i]
    return parts[::-1]


def chunk_words(words: list[dict], max_chars: int, max_words: int, pause_split: float) -> list[dict]:
    """단어들을 한 화면에 보여줄 묶음으로 나눈다."""
    chunks = []
    for phrase in _split_phrases(words, pause_split):
        for ws in _balanced_split(phrase, max_chars, max_words):
            # 쇼츠 자막은 마침표·쉼표 없이 (물음표·느낌표는 유지)
            texts = [w["text"] for w in ws]
            texts[-1] = texts[-1].rstrip(".,")
            chunks.append({"text": " ".join(texts), "words": [dict(w, text=t) for w, t in zip(ws, texts)],
                           "start": ws[0]["start"], "end": ws[-1]["end"]})
    # 다음 자막이 나올 때까지 이어서 보여주기 (깜빡임 방지, 긴 쉼은 0.5초까지만)
    for a, b in zip(chunks, chunks[1:]):
        a["end"] = min(b["start"], a["end"] + 0.5)
    chunks[-1]["end"] += 0.3
    return chunks


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _color(hex_rgb: str) -> str:
    """'#RRGGBB' → ASS 색 '&HBBGGRR&'."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _chunk_events(c: dict, sub: dict) -> list[str]:
    """자막 한 덩어리 → 단어마다 이벤트 하나. 지금 읽는 단어만 강조색, 덩어리 첫 등장 때 톡 튀어나옴."""
    hi = _color(sub["highlight_color"])
    words = c["words"]
    events = []
    for i, w in enumerate(words):
        start = c["start"] if i == 0 else w["start"]
        end = words[i + 1]["start"] if i + 1 < len(words) else c["end"]
        if end <= start:
            continue
        parts = [f"{{\\c{hi}}}{x['text']}{{\\c&HFFFFFF&}}" if j == i else x["text"] for j, x in enumerate(words)]
        pop = "{\\fscx75\\fscy75\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{pop}{' '.join(parts)}")
    return events


def _overlay_style(name: str, o: dict, font: str, vid: dict) -> str:
    """위쪽 고정 표시(순위·항목 이름 등)용 스타일. position_y 지점에 글자 가운데가 오게."""
    margin_v = int(vid["height"] * o["position_y"] - o["font_size"] / 2)
    return (f"Style: {name},{font},{o['font_size']},{_color(o.get('color', '#FFFFFF'))[:-1].replace('&H', '&H00')},"
            f"&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{o.get('outline', 8)},4,8,40,40,{margin_v},1")


def _header_style(o: dict, font: str, vid: dict) -> str:
    """위쪽 사연 제목: 반투명 상자 안에 흰 글씨 (BorderStyle 3 = 글자 뒤 상자). 길면 자동 줄바꿈."""
    alpha = f"{round((1 - o.get('box_alpha', 0.55)) * 255):02X}"
    box = _color(o.get("box_color", "#000000"))[2:-1]
    margin_v = int(vid["height"] * o["position_y"] - o["font_size"] / 2)
    m = o.get("margin", 70)
    return (f"Style: Header,{font},{o['font_size']},{_color(o.get('color', '#FFFFFF'))[:-1].replace('&H', '&H00')},"
            f"&H00FFFFFF,&H{alpha}{box},&H{alpha}{box},0,0,0,0,100,100,0,0,3,18,0,8,{m},{m},{margin_v},1")


def overlay_events(segments: list[dict]) -> list[str]:
    """구간마다 순위(label)와 항목 이름(item)을 위쪽에 표시. 등장할 때 톡 튀어나옴."""
    events = []
    for seg in segments:
        end = seg.get("show_until", seg["end"])
        pop = "{\\fscx60\\fscy60\\t(0,120,\\fscx100\\fscy100)}"
        if seg.get("label"):
            events.append(f"Dialogue: 1,{_ass_time(seg['start'])},{_ass_time(end)},Label,,0,0,0,,{pop}{seg['label']}")
        if seg.get("item"):
            events.append(f"Dialogue: 1,{_ass_time(seg['start'])},{_ass_time(end)},Item,,0,0,0,,{pop}{seg['item']}")
    return events


def build_ass(chunks: list[dict], segments: list[dict] | None = None, layout: dict | None = None,
              header: str | None = None, overrides: dict | None = None) -> str:
    cfg = config.load()
    sub, vid = {**cfg["subtitle"], **(overrides or {})}, cfg["video"]
    layout = layout or {}
    # 화면 위에서 position_y 지점에 자막 가운데가 오도록 (쇼츠 하단 UI와 안 겹치게 가운데보다 약간 아래)
    margin_v = int(vid["height"] * (1 - sub["position_y"]) - sub["font_size"] / 2)
    extra_styles = "".join(
        _overlay_style(name, layout[key], sub["font_name"], vid) + "\n"
        for name, key in (("Label", "label"), ("Item", "item")) if key in layout
    )
    if header and "header" in layout:
        extra_styles += _header_style(layout["header"], sub["font_name"], vid) + "\n"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {vid['width']}
PlayResY: {vid['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{sub['font_name']},{sub['font_size']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{sub['outline']},4,2,60,60,{margin_v},1
{extra_styles}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [e for c in chunks for e in _chunk_events(c, sub)]
    if segments and layout:
        lines += overlay_events(segments)
    if header and "header" in layout:  # 사연 제목은 처음부터 끝까지
        lines.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(chunks[-1]['end'])},Header,,0,0,0,,{header}")
    return head + "\n".join(lines) + "\n"


def make_subtitle(words_json: Path, ass_path: Path, segments: list[dict] | None = None,
                  layout: dict | None = None, header: str | None = None, overrides: dict | None = None) -> Path:
    """segments와 layout을 주면 위쪽 고정 표시(순위 등)도 함께 그린다. overrides: 채널별 자막 설정(강조색 등)."""
    sub = config.load()["subtitle"]
    words = json.loads(words_json.read_text(encoding="utf-8"))
    chunks = chunk_words(words, sub["max_chars"], sub["max_words"], sub["pause_split"])
    if segments:  # 순위 표시는 다음 구간이 시작할 때까지 유지 (구간 사이 쉬는 동안 깜빡이지 않게)
        segments = [dict(s, show_until=n["start"]) for s, n in zip(segments, segments[1:])] + [
            dict(segments[-1], show_until=chunks[-1]["end"])]
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(build_ass(chunks, segments, layout, header, overrides), encoding="utf-8")
    return ass_path


def main():
    ap = argparse.ArgumentParser(description="단어 타이밍 json → 자막 ass")
    ap.add_argument("words_json", type=Path)
    ap.add_argument("ass_path", type=Path)
    args = ap.parse_args()
    out = make_subtitle(args.words_json, args.ass_path)
    print(f"자막: {out}")


if __name__ == "__main__":
    main()
