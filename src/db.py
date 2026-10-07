"""제작 기록 DB (data/history.db, SQLite).

영상마다 한 줄: 채널, 스타일, 주제, 제목, 고유 코드(uid), 결과(done/failed), 파일 위치 등.
- 주제 중복 방지 (planner가 예전 주제를 읽음)
- 판례 재사용 방지 (case_id)
- 8단계: uid로 유튜브 영상과 짝 맞추기

단독 실행 (최근 기록 보기):
    .venv/bin/python -m src.db
"""
import datetime as dt
import secrets
import sqlite3
from contextlib import closing

from src import config

DB_PATH = config.path("data/history.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        TEXT UNIQUE NOT NULL,
    channel    TEXT NOT NULL,
    style      TEXT NOT NULL,
    topic      TEXT,
    title      TEXT,
    status     TEXT NOT NULL,          -- done / failed
    error      TEXT,
    path       TEXT,
    provider   TEXT,
    case_id    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel, created_at);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def new_uid(channel: str) -> str:
    """영상 고유 코드. 예: ja-3f9a1c (채널 앞 두 글자 + 랜덤)."""
    return f"{channel[:2]}-{secrets.token_hex(3)}"


def record(uid: str, channel: str, style: str, status: str, **fields) -> None:
    cols = dict(uid=uid, channel=channel, style=style, status=status,
                created_at=dt.datetime.now().isoformat(timespec="seconds"), **fields)
    with closing(connect()) as con, con:
        con.execute(f"INSERT INTO videos ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    list(cols.values()))


def past_topics(channel: str, style: str | None = None, limit: int = 300) -> list[str]:
    """채널의 예전 주제들 (최근 순). 실패한 것도 포함 (같은 주제를 계속 다시 시도하지 않게)."""
    sql = "SELECT topic FROM videos WHERE channel = ? AND topic IS NOT NULL"
    args = [channel]
    if style:
        sql += " AND style = ?"
        args.append(style)
    with closing(connect()) as con:
        rows = con.execute(sql + " ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()
    return [r["topic"] for r in rows]


def style_counts(channel: str, days: int = 7) -> dict[str, int]:
    """채널의 최근 며칠간 스타일별 성공 개수."""
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    with closing(connect()) as con:
        rows = con.execute("SELECT style, COUNT(*) n FROM videos WHERE channel = ? AND status = 'done' "
                           "AND created_at >= ? GROUP BY style", (channel, since)).fetchall()
    return {r["style"]: r["n"] for r in rows}


def used_case_ids() -> set[str]:
    with closing(connect()) as con:
        return {r["case_id"] for r in con.execute("SELECT case_id FROM videos WHERE case_id IS NOT NULL "
                                                  "AND status = 'done'")}


def main():
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM videos ORDER BY id DESC LIMIT 20").fetchall()
    for r in rows:
        print(f"{r['created_at']} {r['uid']} {r['channel']:8} {r['style']:8} {r['status']:6} {r['title'] or r['topic']}")
    if not rows:
        print("기록 없음")


if __name__ == "__main__":
    main()
