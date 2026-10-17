#!/bin/bash
# cron이 실행: 영상 만들기 + 드라이브 상태 파일 + 오래된 영상 정리
#   예) daily.sh --channel ssul --count 2
#       daily.sh --channel japhak --channel ranklab --count 2
# 다른 작업(15분마다 도는 edits.sh 등)이 잠금을 잡고 있으면 최대 1시간 기다렸다가 실행 (flock -w)
# (예전엔 -n이라 04:00에 edits.sh와 동시에 시작되면 조용히 건너뛰었음: 10-14, 10-17)
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=C.UTF-8
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
exec /usr/bin/flock -w 3600 /tmp/shorts-factory.lock \
  .venv/bin/python -m src.main "$@" --cron >> "logs/cron.log" 2>&1
