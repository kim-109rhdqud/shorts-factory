"""서버 디스크 정리 (드라이브에는 그대로 남음).

- output/<채널>/<날짜>/ : keep_days(기본 14일) 지난 폴더 삭제. 단, 드라이브에 같은 파일이 다 올라가 있을 때만
  (안 올라가 있으면 먼저 올려 보고, 그래도 안 되면 남겨 둠)
- output/_work/ : 하루 지난 중간 파일 삭제 (실패한 작업 찌꺼기)
- logs/ : 60일 지난 로그 삭제

단독 실행:
    .venv/bin/python -m src.cleanup              # 실제 삭제
    .venv/bin/python -m src.cleanup --dry-run    # 무엇을 지울지만 보기
"""
import argparse
import datetime as dt
import logging
import shutil
import subprocess
import time
from pathlib import Path

from src import config, export

log = logging.getLogger("cleanup")

DATE_DIR = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"


def on_drive(folder: Path) -> bool:
    """폴더의 파일이 드라이브에 전부 (같은 크기로) 있는지."""
    out_root = config.path(config.load()["paths"]["output"])
    remote = f"{config.load()['drive']['remote']}/{folder.resolve().relative_to(out_root).as_posix()}"
    renamed = export.drive_names(folder)  # 드라이브에서 제목으로 이름이 바뀐 영상
    excludes = [a for v in renamed for a in ("--exclude", v)]
    r = subprocess.run([config.tool("rclone"), "check", str(folder), remote, "--one-way", "--size-only",
                        "--exclude", "*_project/**", *excludes],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False
    for video, name in renamed.items():
        r = subprocess.run([config.tool("rclone"), "lsf", f"{remote}/{name}"], capture_output=True, text=True)
        if not r.stdout.strip():
            return False
    return True


def old_day_folders(keep_days: int) -> list[Path]:
    out_root = config.path(config.load()["paths"]["output"])
    cutoff = dt.date.today() - dt.timedelta(days=keep_days)
    folders = []
    for d in sorted(out_root.glob(f"*/{DATE_DIR}")):
        if d.parent.name.startswith("_"):
            continue
        if dt.date.fromisoformat(d.name) < cutoff:
            folders.append(d)
    return folders


def cleanup(keep_days: int = 14, dry_run: bool = False) -> dict:
    result = {"deleted": [], "kept": []}
    for d in old_day_folders(keep_days):
        ok = on_drive(d)
        if not ok and not dry_run:
            try:
                export.upload(d)
                ok = on_drive(d)
            except Exception as e:
                log.warning("드라이브 업로드 재시도 실패 %s: %s", d, e)
        if ok:
            result["deleted"].append(str(d))
            if not dry_run:
                shutil.rmtree(d)
                if not any(d.parent.iterdir()):
                    d.parent.rmdir()
        else:
            result["kept"].append(str(d))
            log.warning("드라이브에 없어서 남겨 둠: %s", d)

    now = time.time()
    work = config.path(config.load()["paths"]["work"])
    for p in work.glob("*") if work.exists() else []:
        if p.is_dir() and now - p.stat().st_mtime > 86400:
            result["deleted"].append(str(p))
            if not dry_run:
                shutil.rmtree(p, ignore_errors=True)
    for p in config.path("logs").glob("*.log"):
        if now - p.stat().st_mtime > 60 * 86400:
            result["deleted"].append(str(p))
            if not dry_run:
                p.unlink()
    log.info("정리: 삭제 %d개, 남김 %d개%s", len(result["deleted"]), len(result["kept"]), " (미리보기)" if dry_run else "")
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="오래된 output 정리")
    ap.add_argument("--keep-days", type=int, default=config.load().get("cleanup", {}).get("keep_days", 14))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = cleanup(args.keep_days, args.dry_run)
    for x in r["deleted"]:
        print("삭제" if not args.dry_run else "삭제 예정", x)
    for x in r["kept"]:
        print("남김", x)


if __name__ == "__main__":
    main()
