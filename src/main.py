"""전체 실행: 채널마다 오늘의 주제를 정하고 영상을 만든다.

- 영상 하나가 실패해도 기록만 하고 나머지는 계속 만든다
- AI 로그인 만료 / 하루 호출 상한이면 거기서 멈춘다 (더 해도 계속 실패하니까)
- 모든 결과는 data/history.db, 진행 기록은 logs/<날짜>.log
- 영상은 채널별로 드라이브에 올린다

실행:
    .venv/bin/python -m src.main                      # 모든 채널, 채널 설정의 하루 개수만큼
    .venv/bin/python -m src.main --dry-run            # 영상은 안 만들고 오늘 고른 주제만 보기
    .venv/bin/python -m src.main --channel japhak --count 1
"""
import argparse
import datetime as dt
import logging
import time

from src import channels, config, db, export, llm, planner
from src.make_video import SkipVideo, make_from_topic

log = logging.getLogger("main")


def setup_logging() -> None:
    logs = config.path("logs")
    logs.mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=[
        logging.StreamHandler(),
        logging.FileHandler(logs / f"{dt.date.today().isoformat()}.log", encoding="utf-8"),
    ])


def run(channel_ids: list[str], count: int | None = None, dry_run: bool = False) -> dict:
    """영상 만들기. 돌려주는 것: {"done": [...], "failed": [...], "stopped": 이유 또는 None}"""
    summary = {"done": [], "failed": [], "skipped": [], "stopped": None}
    for cid in channel_ids:
        try:
            plan = planner.plan_channel(cid, count)
        except (llm.AuthExpired, llm.DailyLimit) as e:
            summary["stopped"] = str(e)
            log.error("중단: %s", e)
            break
        except Exception as e:
            log.exception("%s 주제 정하기 실패", cid)
            summary["failed"].append({"channel": cid, "error": f"주제 정하기 실패: {e}"})
            continue
        for item in plan:
            log.info("계획: %s / %s / %s", cid, item["style"], item["topic"] or "(판례 자동 선택)")
        if dry_run:
            summary["done"] += plan
            continue

        uploaded = set()
        for item in plan:
            uid = db.new_uid(cid)
            info, start = {}, time.time()
            try:
                path = make_from_topic(item["topic"], cid, item["style"], uid=uid, result=info, upload=False)
                db.record(uid, cid, item["style"], "done", topic=info.get("topic"), title=info.get("title"),
                          path=str(path), provider=info.get("provider"), case_id=info.get("case_id"))
                uploaded.add(path.parent)
                summary["done"].append({"channel": cid, "uid": uid, "title": info.get("title"), "path": str(path)})
                log.info("완료 %s %s (%.0f초)", uid, info.get("title"), time.time() - start)
            except SkipVideo as e:  # 썰 채널 그림 한도 등: 실패가 아니라 건너뜀, 이 채널의 남은 영상도 건너뜀
                db.record(uid, cid, item["style"], "skipped", topic=info.get("topic") or item["topic"], error=str(e))
                summary["skipped"].append({"channel": cid, "topic": info.get("topic") or item["topic"], "reason": str(e)})
                log.warning("건너뜀 %s: %s", cid, e)
                break
            except (llm.AuthExpired, llm.DailyLimit) as e:
                db.record(uid, cid, item["style"], "failed", topic=info.get("topic") or item["topic"], error=str(e))
                summary["stopped"] = str(e)
                log.error("중단: %s", e)
                break
            except Exception as e:  # 이 영상만 건너뛰고 계속
                log.exception("실패 %s %s", cid, item)
                db.record(uid, cid, item["style"], "failed", topic=info.get("topic") or item["topic"],
                          case_id=info.get("case_id"), error=str(e)[:500])
                summary["failed"].append({"channel": cid, "topic": item["topic"], "error": str(e)[:200]})
        for folder in uploaded:  # 채널의 오늘 폴더를 한 번에 드라이브로
            try:
                log.info("드라이브 업로드: %s", export.upload(folder))
            except Exception as e:
                log.exception("드라이브 업로드 실패")
                summary["failed"].append({"channel": cid, "error": f"드라이브 업로드 실패: {e}"})
        if summary["stopped"]:
            break
    return summary


def flow_todo() -> list[str]:
    """Flow 장면 영상이 아직 다 안 들어온 영상 목록 (최근 7일)."""
    import json
    from src import edits
    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    out = []
    for pfile in edits.projects():
        if pfile.parts[-3] < cutoff:
            continue
        p = json.loads(pfile.read_text(encoding="utf-8"))
        if not p.get("flow"):
            continue
        total, got = len(p.get("scene_images", [])), len(p.get("flow_clips", {}))
        if got < total:
            out.append(f"  🎬 Flow 남음: {pfile.parts[-4]}/{pfile.parts[-3]}/{p['video']} 장면 {got}/{total}개 완료")
    return out


def write_status(s: dict, label: str) -> None:
    """드라이브에 상태 파일(_상태.txt) 올리기: 알림 대신 폰으로 드라이브 볼 때 같이 확인."""
    lines = [f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {label}",
             f"성공 {len(s['done'])}개, 실패 {len(s['failed'])}개, 건너뜀 {len(s.get('skipped', []))}개"]
    if s["stopped"]:
        lines.append(f"⚠️ 중단됨: {s['stopped']}")
        if "로그인" in s["stopped"]:
            lines.append("→ 서버에서 AI 다시 로그인이 필요해요. Claude Code에게 '로그인 만료 해결해줘'라고 말해 주세요.")
    for d in s["done"]:
        lines.append(f"  ✅ {d.get('channel')} {d.get('uid', '')} {d.get('title') or d.get('topic') or ''}")
    for f in s["failed"]:
        lines.append(f"  ❌ {f.get('channel')} {f.get('topic') or ''} {f.get('error', '')[:150]}")
    for k in s.get("skipped", []):
        lines.append(f"  ⏭️ {k.get('channel')} 건너뜀: {k.get('reason', '')[:150]}")
    lines += flow_todo()
    status = config.path("logs/_상태.txt")
    old = status.read_text(encoding="utf-8").split("\n\n")[:13] if status.exists() else []  # 최근 14번만 유지
    status.write_text("\n\n".join(["\n".join(lines)] + old), encoding="utf-8")
    try:
        export.upload_file(status, "_상태.txt")
    except Exception:
        log.exception("상태 파일 업로드 실패")


def main():
    setup_logging()
    ap = argparse.ArgumentParser(description="모든 채널 영상 만들기")
    ap.add_argument("--channel", action="append", help="이 채널만 (여러 번 쓸 수 있음). 없으면 전부")
    ap.add_argument("--count", type=int, help="채널당 개수 (없으면 채널 설정 daily_count)")
    ap.add_argument("--dry-run", action="store_true", help="영상은 안 만들고 주제만 정해 보기")
    ap.add_argument("--cron", action="store_true", help="자동 실행용 (끝나고 오래된 영상 정리)")
    args = ap.parse_args()
    ids = args.channel or channels.list_ids()
    off = [str(d) for d in (config.load().get("schedule") or {}).get("off_days") or []]
    if args.cron and dt.date.today().isoformat() in off:
        log.info("오늘은 쉬는 날 (config.yaml schedule.off_days) → 자동 제작 안 함")
        return
    log.info("시작: 채널 %s%s", ids, " (주제만 보기)" if args.dry_run else "")
    s = run(ids, args.count, args.dry_run)
    log.info("끝: 성공 %d개, 실패 %d개%s", len(s["done"]), len(s["failed"]),
             f", 중단: {s['stopped']}" if s["stopped"] else "")
    for f in s["failed"]:
        log.info("  실패: %s", f)
    if not args.dry_run:
        write_status(s, "자동 실행" if args.cron else "수동 실행")
        if args.cron:  # 자동 실행 때는 오래된 영상도 정리
            from src import cleanup
            try:
                cleanup.cleanup(config.load().get("cleanup", {}).get("keep_days", 14))
            except Exception:
                log.exception("정리 실패")


if __name__ == "__main__":
    main()
