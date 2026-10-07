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
from src.make_video import make_from_topic

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
    summary = {"done": [], "failed": [], "stopped": None}
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


def main():
    setup_logging()
    ap = argparse.ArgumentParser(description="모든 채널 영상 만들기")
    ap.add_argument("--channel", action="append", help="이 채널만 (여러 번 쓸 수 있음). 없으면 전부")
    ap.add_argument("--count", type=int, help="채널당 개수 (없으면 채널 설정 daily_count)")
    ap.add_argument("--dry-run", action="store_true", help="영상은 안 만들고 주제만 정해 보기")
    args = ap.parse_args()
    ids = args.channel or channels.list_ids()
    log.info("시작: 채널 %s%s", ids, " (주제만 보기)" if args.dry_run else "")
    s = run(ids, args.count, args.dry_run)
    log.info("끝: 성공 %d개, 실패 %d개%s", len(s["done"]), len(s["failed"]),
             f", 중단: {s['stopped']}" if s["stopped"] else "")
    for f in s["failed"]:
        log.info("  실패: %s", f)


if __name__ == "__main__":
    main()
