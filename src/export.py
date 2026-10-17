"""완성 영상을 output/<채널>/<날짜>/ 에 저장하고 구글 드라이브로 올린다.

단독 실행 (폴더 하나를 드라이브로 올리기):
    .venv/bin/python -m src.export output/test/2026-10-02
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

from src import config


def day_dir(channel: str, date: dt.date | None = None) -> Path:
    date = date or dt.date.today()
    d = config.path(config.load()["paths"]["output"]) / channel / date.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def next_number(folder: Path) -> str:
    """그 날 폴더의 다음 영상 번호 (001, 002, ...)."""
    nums = [int(p.stem) for p in folder.glob("*.mp4") if p.stem.isdigit()]
    return f"{max(nums, default=0) + 1:03d}"


def save(video: Path, channel: str, upload_text: str = "") -> Path:
    """영상(+ 업로드 정보 txt)을 채널/날짜 폴더에 번호를 붙여 저장."""
    folder = day_dir(channel)
    num = next_number(folder)
    dest = folder / f"{num}.mp4"
    shutil.move(str(video), dest)
    if upload_text:
        (folder / f"{num}_upload.txt").write_text(upload_text, encoding="utf-8")
    return dest


def drive_names(folder: Path) -> dict[str, str]:
    """Flow 장면이 들어간 영상은 드라이브에 '001.mp4' 대신 '<제목>.mp4'로 올린다 (사용자 결정 2026-10-17).
    {서버 파일 이름: 드라이브 파일 이름}. 서버 쪽 이름은 그대로 (재료 폴더·문서가 번호를 씀)."""
    names = {}
    for pfile in folder.glob("*_project/project.json"):
        project = json.loads(pfile.read_text(encoding="utf-8"))
        up = folder / f"{Path(project['video']).stem}_upload.txt"
        if not project.get("rendered_clips") or not up.exists():
            continue
        m = re.search(r"\[제목\]\n([^\n]+)", up.read_text(encoding="utf-8"))
        title = re.sub(r'[\\/:*?"<>|]', "", m.group(1)).strip() if m else ""
        if title:
            names[project["video"]] = f"{title}.mp4"
    return names


def upload(folder: Path) -> str:
    """output 기준 같은 경로로 드라이브에 복사. 드라이브 경로를 돌려준다."""
    out_root = config.path(config.load()["paths"]["output"])
    remote = f"{config.load()['drive']['remote']}/{folder.resolve().relative_to(out_root).as_posix()}"
    rclone, renamed = config.tool("rclone"), drive_names(folder)
    excludes = [a for v in renamed for a in ("--exclude", v)]
    subprocess.run([rclone, "copy", str(folder), remote, "--exclude", "_work/**",
                    "--exclude", "*_project/**", *excludes], check=True)  # 재료 폴더는 서버에만 (대본 문서는 따로 올림)
    for video, name in renamed.items():
        subprocess.run([rclone, "copyto", str(folder / video), f"{remote}/{name}"], check=True)
        subprocess.run([rclone, "deletefile", f"{remote}/{video}"], capture_output=True)  # 번호 이름 옛 파일
    return remote


def upload_file(path: Path, name: str) -> str:
    """파일 하나를 드라이브 shorts-factory/ 바로 아래에 name으로 올린다 (상태 파일 등)."""
    remote = f"{config.load()['drive']['remote']}/{name}"
    subprocess.run([config.tool("rclone"), "copyto", str(path), remote], check=True)
    return remote


def main():
    ap = argparse.ArgumentParser(description="폴더를 구글 드라이브로 업로드")
    ap.add_argument("folder", type=Path)
    args = ap.parse_args()
    print(f"업로드 완료: {upload(args.folder)}")


if __name__ == "__main__":
    main()
