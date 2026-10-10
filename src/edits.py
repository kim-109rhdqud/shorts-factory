"""대본 직접 수정 → 영상 다시 만들기.

영상을 만들 때 다시 만드는 데 필요한 재료(대본, 장면 그림, 음악, 설정)를
output/<채널>/<날짜>/<번호>_project/ 에 보관하고, 드라이브에 "<번호>_대본" 구글 문서를 올린다.
사용자가 그 문서를 고치면 check()가 알아채서 그 영상만 다시 만든다 (목소리·자막·타이밍 자동, 그림은 재사용).
cron이 15분마다 check를 돌린다.

실행:
    .venv/bin/python -m src.edits check          # 고친 문서가 있으면 영상 다시 만들기
    .venv/bin/python -m src.edits list           # 수정 가능한 영상 목록
"""
import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from src import background, channels, config, export, music, render, script, subtitle, tts

log = logging.getLogger("edits")

DOC_HELP = ("이 문서를 고치면 15분 안에 영상이 다시 만들어집니다.\n"
            "[ ] 로 된 제목 줄은 지우지 말고, 그 아래 글만 고치세요.\n")


def _remote(path: Path) -> str:
    out_root = config.path(config.load()["paths"]["output"])
    return f"{config.load()['drive']['remote']}/{path.resolve().relative_to(out_root).as_posix()}"


def doc_name(video: Path) -> str:
    return f"{video.stem}_대본.txt"


# ---------- 문서 ↔ 대본 ----------

def to_doc(header: str | None, segments: list[dict]) -> str:
    parts = [DOC_HELP]
    if header is not None:
        parts.append(f"[화면 제목]\n{header}\n")
    for seg in segments:
        if seg.get("label"):
            parts.append(f"[{seg['label']} 요약]\n{seg.get('item', '')}\n")
            parts.append(f"[{seg['label']}]\n{seg['text']}\n")
        else:
            parts.append(f"[{'사연' if len(segments) > 1 else '대본'}]\n{seg['text']}\n")
    return "\n".join(parts)


def from_doc(text: str, old_segments: list[dict]) -> tuple[str | None, list[dict]]:
    """문서 → (화면 제목, 구간 목록). 구간 순서·라벨은 원래 것을 따른다."""
    text = text.lstrip("﻿")
    sections = dict(re.findall(r"^\[([^\]\n]+)\]\s*\n(.*?)(?=^\[[^\]\n]+\]\s*$|\Z)", text, re.S | re.M))
    sections = {k.strip(): " ".join(v.split()) for k, v in sections.items()}
    header = sections.get("화면 제목")
    segs = []
    for seg in old_segments:
        if seg.get("label"):
            body = sections.get(seg["label"], seg["text"])
            item = sections.get(f"{seg['label']} 요약", seg.get("item", ""))
            segs.append({**seg, "text": body, "item": item})
        else:
            key = "사연" if len(old_segments) > 1 else "대본"
            segs.append({**seg, "text": sections.get(key, seg["text"])})
    return header, segs


def _hash(header: str | None, segments: list[dict]) -> str:
    raw = json.dumps([header] + [[s.get("item", ""), s["text"]] for s in segments], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()


# ---------- 보관 ----------

def save_project(video: Path, project: dict, scene_images: list[Path | None], upload: bool) -> Path:
    """영상 옆에 재료 폴더를 만들고, 드라이브에 대본 문서를 올린다."""
    pdir = video.with_name(f"{video.stem}_project")
    pdir.mkdir(exist_ok=True)
    names = []
    for i, img in enumerate(scene_images or []):
        if img and Path(img).exists():
            dest = pdir / f"scene{i + 1}{Path(img).suffix}"
            shutil.copy2(img, dest)
            names.append(dest.name)
        else:
            names.append(None)
    project = {**project, "scene_images": names, "video": video.name, "flow_clips": {},
               "rendered_hash": _hash(project.get("header"), project["segments"]),
               "created": dt.datetime.now().isoformat(timespec="seconds"), "edits": 0}
    (pdir / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    doc = pdir / doc_name(video)
    doc.write_text(to_doc(project.get("header"), project["segments"]), encoding="utf-8")
    if upload:
        upload_doc(video, doc)
        if project.get("flow"):
            upload_flow_work(video, pdir, project)
    return pdir


# ---------- Flow 작업 (사용자가 Flow에서 장면 영상을 만들어 드라이브 폴더에 넣음) ----------

VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")


def flow_folder(video: Path) -> str:
    return f"{_remote(video.parent)}/{video.stem}_flow"


def flow_prompt(scene: dict, flow_cfg: dict) -> str:
    return f"{scene.get('motion') or scene.get('image', '')} {flow_cfg.get('style_suffix', '')}".strip()


def upload_flow_work(video: Path, pdir: Path, project: dict) -> None:
    """드라이브에 <번호>_flow/ 폴더(시작 그림)와 <번호>_Flow작업 문서(장면별 문장)를 올린다."""
    flow_cfg, scenes = project["flow"], project.get("scenes", [])
    rclone = config.tool("rclone")
    for i, name in enumerate(project.get("scene_images", []), 1):
        if name:
            subprocess.run([rclone, "copyto", str(pdir / name), f"{flow_folder(video)}/시작그림_{i}{Path(name).suffix}"],
                           check=True)
    lines = [f"Flow 작업: {video.stem}번 영상 (장면 {len(scenes)}개)",
             f"설정: {flow_cfg.get('setting', '')}",
             "",
             "하는 방법",
             f"1. 드라이브 {video.stem}_flow 폴더에서 '시작그림_1'을 받는다",
             "2. Flow에서 그림을 넣고, 아래 '장면 1' 문장을 그대로 복사해 붙여 넣고 생성한다",
             f"3. 만든 영상을 {video.stem}_flow 폴더에 '장면1' 이라는 이름으로 넣는다 (번호만 맞으면 됨)",
             "4. 장면 6까지 반복. 다 안 해도 넣은 장면부터 영상에 들어간다 (15분마다 확인)",
             ""]
    for i, sc in enumerate(scenes, 1):
        lines += [f"[장면 {i}] 시작그림_{i}", flow_prompt(sc, flow_cfg), ""]
    doc = pdir / f"{video.stem}_Flow작업.txt"
    doc.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run([rclone, "copyto", str(doc), f"{_remote(video.parent)}/{doc.name}",
                    "--drive-import-formats", "txt", "--drive-export-formats", "txt"], check=True)


def _scene_number(name: str) -> int | None:
    m = re.search(r"(\d+)", Path(name).stem)
    return int(m.group(1)) if m else None


def fetch_flow_clips(pfile: Path, project: dict) -> bool:
    """드라이브 <번호>_flow 폴더에 새로 들어온(또는 바뀐) 장면 영상을 받아 온다. 새 게 있으면 True."""
    video = pfile.parent.parent / project["video"]
    r = subprocess.run([config.tool("rclone"), "lsjson", flow_folder(video)], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    changed, clips = False, dict(project.get("flow_clips", {}))
    for f in json.loads(r.stdout or "[]"):
        n = _scene_number(f["Name"])
        if f.get("IsDir") or not f["Name"].lower().endswith(VIDEO_EXT) or not n:
            continue
        key = f"{f.get('ID')}:{f.get('Size')}:{f.get('ModTime')}"
        if clips.get(str(n), {}).get("key") == key:
            continue
        dest = pfile.parent / "flow" / f"scene{n}{Path(f['Name']).suffix.lower()}"
        dest.parent.mkdir(exist_ok=True)
        subprocess.run([config.tool("rclone"), "copyto", f"{flow_folder(video)}/{f['Name']}", str(dest)], check=True)
        clips[str(n)] = {"key": key, "file": str(dest.relative_to(pfile.parent)), "name": f["Name"]}
        log.info("Flow 장면 %d 받음: %s", n, f["Name"])
        changed = True
    if changed:
        project["flow_clips"] = clips
        pfile.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed


def upload_doc(video: Path, doc: Path) -> None:
    """텍스트를 구글 문서로 올린다 (폰·브라우저에서 바로 고칠 수 있게)."""
    subprocess.run([config.tool("rclone"), "copyto", str(doc), f"{_remote(video.parent)}/{doc.name}",
                    "--drive-import-formats", "txt", "--drive-export-formats", "txt"], check=True)


def read_doc(video: Path) -> str | None:
    r = subprocess.run([config.tool("rclone"), "cat", f"{_remote(video.parent)}/{doc_name(video)}",
                        "--drive-export-formats", "txt"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def projects() -> list[Path]:
    out_root = config.path(config.load()["paths"]["output"])
    return sorted(p for p in out_root.glob("*/*/*_project/project.json") if not p.parts[-4].startswith("_"))


# ---------- 다시 만들기 ----------

def rerender(pfile: Path, header: str | None, segments: list[dict]) -> Path:
    """고친 대본으로 영상만 다시 만든다. 그림·음악·배경은 처음 것을 다시 쓴다."""
    project = json.loads(pfile.read_text(encoding="utf-8"))
    pdir, cfg = pfile.parent, config.load()
    st, ch = script.style_config(project["style"]), channels.load(project["channel"])
    voice, rate, pitch = channels.voice_for(ch, project.get("narrator"))
    if not voice and project.get("narrator") and st.get("voices"):
        voice = st["voices"].get(project["narrator"])
    segments = [dict(s, text=script.fix_counters(s["text"])) for s in segments]
    work = config.path(cfg["paths"]["work"]) / f"edit_{project['channel']}_{dt.datetime.now():%Y%m%d_%H%M%S}"
    try:
        mp3, words, times = tts.synthesize_segments(segments, work, st.get("segment_pause", 0.3),
                                                    voice=voice, rate=rate, pitch=pitch)
        ass = subtitle.make_subtitle(words, work / "sub.ass", times, st.get("layout"), header, ch.get("subtitle"))
        duration = render.audio_duration(mp3) + 1.0
        pics = [pdir / n if n else None for n in project.get("scene_images", [])]
        flow = project.get("flow_clips", {})
        clips = [pdir / flow[str(i)]["file"] if str(i) in flow else None for i in range(1, len(pics) + 1)]
        if pics and (any(pics) or any(clips)):
            starts = background.scene_starts(project.get("scenes", []), " ".join(s["text"] for s in segments),
                                             json.loads(words.read_text(encoding="utf-8")), duration)
            bg = background.make_from_images(pics, starts[:len(pics)], duration, work / "bg.mp4",
                                             seed=project.get("seed"), clips=clips)
        else:
            per_segment = times if st.get("background") == "per_segment" else None
            bg = background.make_background(duration, work / "bg.mp4", project.get("bg_pool"),
                                            seed=project.get("seed"), segments=per_segment)
        track = config.path(project["music"]) if project.get("music") else None
        video = render.render(mp3, ass, work / "video.mp4", bg=bg, music=track)
        final = pdir.parent / project["video"]
        shutil.move(str(video), final)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 업로드 정보의 [대본] 부분도 고친 대본으로
    up = final.with_name(f"{final.stem}_upload.txt")
    if up.exists():
        body = "\n".join(f"[{s['label']} {s.get('item', '')}] {s['text']}" if s.get("label") else s["text"]
                         for s in segments)
        text = up.read_text(encoding="utf-8")
        text = re.sub(r"\[대본\]\n.*?(?=\n\n\[|\Z)", lambda m: f"[대본]\n{body}", text, flags=re.S)
        if header:
            text = re.sub(r"\[화면 위 제목\]\n[^\n]*", lambda m: f"[화면 위 제목]\n{header}", text)
        up.write_text(text, encoding="utf-8")
    project.update(segments=segments, header=header, rendered_hash=_hash(header, segments),
                   rendered_clips={k: v["key"] for k, v in project.get("flow_clips", {}).items()},
                   edits=project.get("edits", 0) + 1, last_edit=dt.datetime.now().isoformat(timespec="seconds"))
    pfile.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    export.upload(final.parent)
    return final


def check() -> list[str]:
    """드라이브의 대본 문서가 바뀌었거나 Flow 장면 영상이 새로 들어온 영상만 다시 만든다."""
    done = []
    for pfile in projects():
        project = json.loads(pfile.read_text(encoding="utf-8"))
        video = pfile.parent.parent / project["video"]
        text = read_doc(video)
        if text is None:
            continue
        header, segs = from_doc(text, project["segments"])
        if project.get("flow"):
            fetch_flow_clips(pfile, project)
        rendered = project.get("rendered_clips", {})
        new_clips = {k: v["key"] for k, v in project.get("flow_clips", {}).items()} != rendered
        if _hash(header, segs) == project.get("rendered_hash") and not new_clips:
            continue
        log.info("%s → 다시 만들기: %s", "Flow 장면 도착" if new_clips else "대본 수정 감지", video)
        try:
            rerender(pfile, header, segs)
            done.append(str(video))
        except Exception:
            log.exception("다시 만들기 실패: %s", video)
    return done


def main():
    logs = config.path("logs")
    logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(logs / f"{dt.date.today().isoformat()}.log", encoding="utf-8")])
    ap = argparse.ArgumentParser(description="대본 문서 수정 → 영상 다시 만들기")
    ap.add_argument("cmd", choices=["check", "list"])
    args = ap.parse_args()
    if args.cmd == "list":
        for p in projects():
            d = json.loads(p.read_text(encoding="utf-8"))
            print(p.parent.parent / d["video"], "| 수정", d.get("edits", 0), "번")
    else:
        done = check()
        log.info("다시 만든 영상 %d개", len(done))


if __name__ == "__main__":
    main()
