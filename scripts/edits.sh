#!/bin/bash
# cron이 15분마다 실행: 드라이브의 "<번호>_대본" 문서가 고쳐졌으면 그 영상만 다시 만들기
# 영상 제작이 돌고 있으면 겹치지 않게 이번 차례는 건너뜀 (같은 잠금 파일)
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=C.UTF-8
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
exec /usr/bin/flock -n /tmp/shorts-factory.lock .venv/bin/python -m src.edits check >> "logs/cron.log" 2>&1
