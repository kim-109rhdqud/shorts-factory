#!/bin/bash
# cron이 실행: 영상 만들기 + 드라이브 상태 파일 + 오래된 영상 정리
#   예) daily.sh --channel ssul --count 2
#       daily.sh --channel japhak --channel ranklab --count 2
# 앞 실행이 아직 안 끝났으면 겹치지 않게 건너뜀 (flock)
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=C.UTF-8
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
exec /usr/bin/flock -n /tmp/shorts-factory.lock \
  .venv/bin/python -m src.main "$@" --cron >> "logs/cron.log" 2>&1
