#!/bin/bash
# cron이 하루 두 번 실행: 채널마다 1개씩 영상 만들기 + 상태 파일 + 오래된 영상 정리
# 앞 실행이 아직 안 끝났으면 겹치지 않게 기다리지 않고 건너뜀 (flock)
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=C.UTF-8
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
exec /usr/bin/flock -n /tmp/shorts-factory.lock \
  .venv/bin/python -m src.main --count "${1:-1}" --cron >> "logs/cron.log" 2>&1
