# shorts-factory

여러 유튜브 채널용 쇼츠를 **주제 선정부터 편집 완료까지 완전 자동으로** 만들어 저장소(구글 드라이브)에 쌓아두는 시스템.
업로드는 사람이 폰으로 확인 후 직접 한다. 업로드된 영상의 성과를 수집해 다음 제작 방향을 스스로 조정한다.

---

## 1. 확정된 방향

- **개발과 운영 모두 클라우드 리눅스 서버에서** 진행
  - 사용자는 주로 PC방에서 작업 → PC방 컴퓨터에는 아무것도 설치하지 않음. **PC방에서는 PowerShell/터미널이 막혀 있어 브라우저만 사용 가능**
  - 처음 세팅: 서버 업체의 **브라우저 웹 콘솔**로 접속
  - 평소 작업: 서버에 설치한 **code-server**(브라우저용 VS Code)에 접속 → 그 안의 터미널에서 Claude Code 실행
  - 코드, 영상, Claude Code 대화 기록이 전부 서버에 남아 어디서 접속해도 이어서 작업
  - 테스트 영상은 구글 드라이브로 보내 폰/브라우저로 확인
- **운영**: 같은 서버에서 cron으로 매일 자동 실행 (사용자 PC 꺼져 있어도 동작)
- **대본 생성**: 유료 API 키 사용 안 함. 서버에 설치된 **Antigravity CLI**(`agy -p`)를 헤드리스 모드로 호출 (사용자의 Google AI Pro 구독 사용)
  - Gemini CLI는 2026-06-18부터 개인 계정 지원이 종료되어 Antigravity CLI로 대체함
  - Antigravity 실패/한도 초과 시 **Claude Code 헤드리스 모드**(`claude -p`)로 자동 전환
  - Claude Code 구독은 개발용으로 아껴야 하므로 대본 생성은 Antigravity(Gemini 모델)가 주력
- **음성·자막·합성**: 전부 로컬 처리 (edge-tts, FFmpeg)
- **결과 전달**: 채널별 날짜 폴더에 저장 → 구글 드라이브 동기화 → 사용자가 폰으로 확인·업로드
- **성과 수집**: YouTube Data/Analytics API (읽기 전용, 업로드 권한 없음)
- **채널**: 여러 채널 운영. 2~3개로 시작

## 2. 역할 분담

| 누가 | 하는 일 |
|---|---|
| 사용자 | 채널 개설, 채널 설정 파일 작성, 완성 영상 확인, 업로드, 로그인 만료 시 재로그인 |
| 프로그램 | 스타일·주제 선정, 대본·제목·설명·해시태그, 음성, 자막, 영상 합성, 드라이브 저장, 성과 수집·분석, 실패 알림 |

## 3. 하루 자동 실행 흐름

1. 서버의 cron이 정해진 시간에 `main` 실행
2. 분석 모듈이 기존 영상 성과 업데이트
3. 채널마다 기획 모듈이 오늘 만들 스타일·주제 결정 (중복 주제 제외)
4. 영상마다: 대본 → 음성 → 자막 → 배경 → 합성
5. 결과를 `output/<채널>/<날짜>/`에 저장 후 드라이브 동기화
6. 로그 기록, 완료/실패 알림 (디스코드 또는 텔레그램, 선택)

## 4. 모듈 구성 (`src/`)

| 모듈 | 역할 |
|---|---|
| `planner` | 채널 설정 + 성과 데이터 + 주제 기록을 보고 오늘 만들 스타일·주제 결정 |
| `llm` | Antigravity CLI / Claude Code CLI 호출 래퍼. 자동 전환, 재시도, 하루 호출 상한, 호출 간격, 인증 만료 감지 |
| `script` | 대본·제목·설명·해시태그를 JSON으로 생성하고 검증 (형식 깨짐, 길이 부족 시 재요청) |
| `tts` | edge-tts로 음성 생성 + 타이밍 정보 저장 |
| `subtitle` | 타이밍 정보로 쇼츠식 자막 생성 (필요 시 Whisper로 보완) |
| `background` | 스타일에 맞는 배경 소스 선택, 9:16으로 자르고 길이 맞춤 |
| `render` | FFmpeg으로 배경 + 음성 + 자막 + 배경음악 합성 → mp4 |
| `export` | 채널/날짜 폴더에 영상 + 업로드 정보 저장, 드라이브 동기화 |
| `analytics` | YouTube API로 채널별 영상 성과 수집 → DB 저장 |
| `main` | 전체 실행 관리, 로그, 알림 |

## 5. 채널 설정 (`channels/*.yaml`)

채널 하나 = 파일 하나. 새 채널 추가는 파일 추가만으로 가능해야 한다.

```yaml
name: 잡지식채널
styles: [잡지식, 랭킹]
language: ko
voice: ko-KR-InJoonNeural
speech_rate: "+10%"
length_sec: 40
daily_count: 2
background_pool: assets/backgrounds/nature
music_pool: assets/music/calm
youtube_channel_id: ""
banned_topics: [정치, 의료정보]
```

- 채널끼리 스타일·주제·목소리·배경을 확실히 다르게 (같은 콘텐츠 돌려쓰기 금지)
- 한 채널 안에서는 스타일 일관성 유지

## 6. 스타일 템플릿 (`templates/`)

템플릿 하나 = 대본 프롬프트 파일 + 화면 레이아웃 코드. 처음엔 3~5종.

| 스타일 | 대본 형식 | 화면 구성 |
|---|---|---|
| 잡지식 | 훅 질문 → 설명 → 반전/마무리 | 배경 영상 + 가운데 큰 자막 |
| 랭킹 TOP 5 | 5위 → 1위 카운트다운 | 순위 숫자 크게 + 항목별 배경 전환 |
| 썰 | 1인칭 사연, 기승전결 | 위: 제목 / 아래: 루프 배경 |
| 퀴즈 | 문제 → 3초 카운트다운 → 정답 | 문제 자막 + 타이머 |
| 명언 | 명언 → 짧은 해설 | 감성 배경 + 강조 자막 |

## 7. 성과 기반 자동 조정

- 수집 지표: 조회수, 평균 시청 지속률, 좋아요, 구독 증가 (업로드 후 1·3·7일)
- 실험기(처음 2~4주): 채널 내 스타일 후보를 골고루 제작
- 수렴기: 성과 좋은 스타일·주제 비중 증가, 약 20%는 계속 새로운 시도
- 잘 된 영상 제목·주제를 대본 프롬프트에 참고 자료로 전달
- 연결 방법: 업로드 정보 텍스트에 고유 ID를 넣고, 영상 제목·설명과 매칭

## 8. 폴더 구조

```
shorts-factory/
  CLAUDE.md
  channels/
  templates/
  assets/
    backgrounds/   # 무료 라이선스 소스만
    music/         # 무료 라이선스 소스만
    fonts/
  output/
    <채널명>/<YYYY-MM-DD>/
      001.mp4
      001_upload.txt   # 제목, 설명, 해시태그, 고유 ID
  data/
    history.db     # SQLite: 제작 기록, 주제 중복 방지, 성과
  logs/
  src/
  .env             # 비밀 정보. 절대 커밋 금지
  .gitignore
```

## 9. 기술 스택

| 영역 | 도구 |
|---|---|
| 언어 | Python 3.11+ |
| 대본 | Antigravity CLI `agy` (주력), Claude Code CLI (예비) |
| 음성 | edge-tts |
| 자막 타이밍 | edge-tts 타이밍 정보, 필요 시 Whisper |
| 영상 합성 | FFmpeg |
| DB | SQLite |
| 성과 수집 | YouTube Data API / YouTube Analytics API (읽기 전용) |
| 서버 | 클라우드 리눅스 서버 (Ubuntu 24.04 권장, CPU 4코어 / 메모리 8GB, GPU 불필요). **브라우저 웹 콘솔이 편한 업체**로 선택 (예: AWS Lightsail, DigitalOcean) |
| 접속 | 초기: 업체 웹 콘솔 / 평소: code-server (HTTPS, 443 포트, 강한 비밀번호) + 서버의 `tmux` (접속 끊겨도 작업 유지) |
| 스케줄 | cron |
| 드라이브 동기화 | rclone |
| 알림 (선택) | 디스코드 웹훅 / 텔레그램 봇 |

## 10. 개발 로드맵

각 단계는 완료 기준을 만족해야 다음으로 넘어간다. **현재 단계는 맨 아래에 기록.**

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 0 | 서버 대여 → 웹 콘솔 접속 → 보안 설정(방화벽, fail2ban) → Claude Code 설치 → **code-server + HTTPS 세팅** → tmux, Python, FFmpeg, Git, Node.js, Antigravity CLI, rclone 구글 드라이브 연결 | PC방 브라우저로 code-server 접속 가능, 각 도구 버전 확인, 테스트 파일이 드라이브에 올라감 |
| 1 | 영상 한 편 만들기 | 직접 쓴 대본 txt → 자막 달린 세로 mp4 |
| 2 | 품질 다듬기 | 자막 디자인·배경음악·배경 랜덤 선택, 폰으로 봐도 자연스러움 |
| 3 | 대본 자동화 | 주제 한 줄 → Antigravity CLI 대본 → 완성 영상. Claude 자동 전환 동작 |
| 4 | 스타일 템플릿 | 3종 이상 템플릿으로 각각 영상 생성 |
| 5 | 다채널 | 채널 설정 2~3개, 채널별 폴더 저장 |
| 6 | 주제 자동 선정 + 중복 방지 | 입력 없이 실행해도 매번 새 주제 |
| 7 | cron 자동 실행 | 1주일 매일 자동 실행, 실패 시 로그·알림 |
| 8 | 성과 수집 | 채널별 통계가 DB에 매일 쌓임 |
| 9 | 성과 기반 선택 | 성과 좋은 스타일·주제 비중 자동 증가 |
| 선택 | 확인용 화면, 업로드 자동화 | 필요 시 |

## 11. 안정성 장치 (필수)

- LLM 호출: 하루 상한, 호출 간격, 재시도, Antigravity → Claude 자동 전환
- 인증 만료 감지 시 제작 중단 + 알림 (재로그인 후 재개)
- 모든 단계 로그 기록, 실패한 영상만 건너뛰고 나머지는 계속 진행
- 오래된 output 자동 정리 (디스크 관리)
- 대본 검증: JSON 형식, 길이, 금지 주제 체크

## 12. 리스크

- 반복·대량 생산 콘텐츠는 수익화 거절 위험 → 대본 구조·연출에 변화, 템플릿 다양화
- 저작권 → 배경·음악은 무료 라이선스 소스만, 남의 글·게임 영상 금지
- 채널 연쇄 정지 → 채널 간 콘텐츠 차별화, 금지 주제 목록
- AI 대본 오류 → 업로드 전 사람 확인, 민감 주제 금지
- 구독 CLI 자동화 사용 → 각 서비스 이용약관과 사용량 한도 확인 후 하루 제작량 결정

---

## Claude Code 작업 규칙

- 사용자는 코드에 익숙하지 않다. 설명은 쉽게, 한국어로.
- **한 번에 한 단계만** 진행한다. 큰 작업 전에는 계획을 먼저 보여주고 확인받는다.
- 각 단계가 끝나면 사용자가 **직접 결과물(음성, 영상)을 확인**할 수 있게 파일 위치와 확인 방법을 알려준다.
- 실행 환경은 **리눅스 서버**다. `pathlib` 사용, 경로 하드코딩 금지, 외부 도구는 `subprocess`로 호출하고 실행 파일 경로는 설정으로 뺀다.
- 사용자는 **PC방 브라우저로 code-server에 접속**해서 작업한다 (로컬 터미널 사용 불가). 사용자에게 로컬 PC에서 명령어를 실행하라고 안내하지 않는다. 결과 확인이 필요하면 **구글 드라이브로 올려서** 확인하게 한다.
- 오래 걸리는 작업은 `tmux` 세션 안에서 실행해 브라우저 탭이 닫혀도 계속되게 한다.
- 서버 보안: code-server는 HTTPS + 강한 비밀번호 필수, 방화벽(ufw)으로 필요한 포트만 개방(443 등), fail2ban 적용. PC방 컴퓨터에 비밀 정보를 저장하게 하는 방식은 쓰지 않는다 (브라우저 비밀번호 저장 금지).
- 유료 API 키를 쓰는 방식으로 구현하지 않는다. LLM은 CLI 호출로만.
- 비밀 정보는 `.env`에만. `.env`, `output/`, `data/`, `logs/`는 `.gitignore`에 포함.
- 모듈은 독립적으로 테스트 가능하게 만든다 (각 모듈 단독 실행 가능).
- 단계 완료 후 사용자 확인을 받으면 커밋하고 GitHub(비공개 저장소)에 푸시한다.
- 단계가 끝나면 아래 "현재 진행 상황"을 업데이트한다.

## 아직 정할 것

- 영상 길이 (30 / 40 / 60초)
- 퀴즈·명언 스타일: 프로젝트가 커진 뒤에 추가 (사용자 결정, 2026-10-05)
- AI 영상 배경 (유료 Veo 등): 보류. 수익이 나면 썰 채널의 중요 장면(첫 장면·판결)만 영상으로 바꾸는 것 검토
  - 참고 비용: Veo Lite 약 $0.05/초. 썰 채널 장면마다 영상이면 월 15~25만 원, 첫 장면만이면 월 4~5만 원

## 현재 진행 상황

- 현재 단계: 7 — 자동 제작 재개 (2026-10-12): 판례 채널 ssul, 월~토 04:00 1편 + Flow 장면은 사용자가 수동 제작. 8단계(성과 수집)·법제처 본인 계정은 대기 (사용자 결정)
- 메모:
  - 서버: AWS Lightsail 서울, 고정 IP 15.165.80.188, 2코어/2GB + 스왑 2GB (권장 사양보다 작음, 영상 합성 때 확인 필요)
  - code-server: https://15-165-80-188.sslip.io (Caddy 자동 HTTPS → 127.0.0.1:8080)
  - 방화벽 ufw: 22, 80, 443만 개방 / fail2ban(sshd) 적용
  - 설치 완료: FFmpeg 6.1.1, Node.js 24, Antigravity CLI 1.2.14 (`~/.local/bin/agy`, Google AI Pro 로그인), Claude Code
  - `agy -p`, `claude -p` 헤드리스 호출 모두 동작 확인
  - rclone 1.75: 리모트 이름 `gdrive`, 권한 `drive` + `root_folder_id` = 드라이브 `shorts-factory/` 폴더 (2026-10-10 변경: 사용자가 올린 Flow 영상을 읽기 위해. 리모트 `gdrive:`가 곧 shorts-factory 폴더, config.yaml `drive.remote: "gdrive:"`. 이전 설정 백업 `~/.config/rclone/rclone.conf.bak-drivefile`)
    - 전용 OAuth 클라이언트 사용 (구글 클라우드 프로젝트 `shorts-factory`, 앱 게시 상태 = 프로덕션 → 토큰 7일 만료 없음)
    - OAuth 동의 화면용 홈페이지/개인정보처리방침: `/var/www/app/` (Caddy가 `/app/*` 경로로 제공)
  - 서버에서 로그인 필요할 때: 로그인 주소를 사용자에게 주고, 돌아온 코드나 주소를 받아 서버에서 대신 입력 (tmux send-keys / curl 127.0.0.1:53682)
  - 1단계: `.venv/bin/python -m src.make_video 대본.txt --channel 채널` → `output/<채널>/<날짜>/NNN.mp4` + 드라이브 업로드
    - 43초 영상 합성 약 70초, 최대 메모리 약 370MB (그라데이션 배경 기준)
    - 목소리: 당분간 edge-tts `ko-KR-InJoonNeural` 유지 (사용자 결정). 유료 TTS(타입캐스트·일레븐랩스 등)는 채널 성과가 나면 재검토
    - 주의: edge-tts는 MS 읽어주기 비공식 사용 → 수익 채널 장기 사용은 약관상 애매. 유료 전환 시 `tts` 모듈만 교체
    - 자막 폰트: Pretendard ExtraBold (OFL, `assets/fonts/`)
  - 2단계 사용자 피드백 (2026-10-02): 배경·음악·자막은 좋음. 말하기가 너무 느림 → 속도 +35%로 변경 (사용자 선택). 테스트 대본은 "쓰레기 같다"(교과서처럼 밋밋함)
    - 3단계 대본 기준: 첫 1~2초 강한 훅, 설명조 말투 금지, 짧고 리듬감 있는 구어체, 중간에 궁금증 유발, 반전·마무리 한 방
  - 2단계: 배경 = Pixabay 무료 세로 영상 (`assets/backgrounds/<풀>`, 키는 .env `PIXABAY_API_KEY`, Pexels는 키 발급 중단으로 사용 못 함), 음악 = Kevin MacLeod CC BY 4.0 (`assets/music/<풀>`, 출처 문구 `NNN_upload.txt`에 자동 삽입)
    - 소스 받기: `.venv/bin/python -m src.fetch_assets music|backgrounds`
    - 영상 하나 약 1분 40초, 최대 메모리 약 410MB
    - 속도 +35%면 초당 약 5.9자 (공백 제외) → 40초 영상 = 대본 약 210~260자
  - 3단계: `.venv/bin/python -m src.make_video --topic "주제"` → AI 대본 → 영상. `--script 파일.txt`로 직접 쓴 대본도 가능
    - `src/llm.py`: agy → claude 자동 전환, 하루 상한(agy 40·claude 10), 재시도, 로그인 만료 감지(AuthExpired), 사용량 `data/llm_usage.json`
    - LLM은 프로젝트 밖 빈 폴더(`~/.local/share/shorts-factory/llm_sandbox`)에서 실행 (CLAUDE.md 등 읽지 않게)
    - agy는 에이전트라 글자 수를 세려고 명령을 실행하려다 막히면 빈 답을 냄 → 프롬프트 앞에 "도구 사용 금지" 지시 (`AGY_PREFIX`)
    - agy `--json-schema`는 엉뚱한 값을 채워서 안 씀 → "JSON만 출력" 지시 후 직접 꺼내서 검사
    - 대본 = 생성(templates/<스타일>/prompt.md) + 검토(templates/_review.md: 사실·과장·상투어 수정, 말투 유지). 영상 하나에 LLM 2회
    - 업로드 정보 txt: 제목, 설명, 해시태그, 업로드 전 사실 확인 목록, 대본, 음악 출처
    - 강제 실패 테스트: `SHORTS_LLM_FORCE_FAIL=agy`
  - 4단계: 스타일 = `templates/<스타일>/prompt.md` + `style.yaml` (길이, 구간 여부, 화면 배치, 목소리, 안내 문구). 완료: trivia(잡지식), ranking(랭킹 TOP 5), story(썰)
    - 실행: `--topic "주제" --style ranking|story|trivia`
    - 대본은 항상 segments(구간) 목록으로 정리 → 구간별 음성 생성·연결, 구간 시간으로 순위 표시·배경 전환
    - 랭킹: AI가 항목마다 영어 bg_query → Pixabay 검색 (태그에 핵심 단어가 모두 있어야 채택, 없으면 끝 명사로, 그래도 없으면 풀). 받은 영상은 `assets/backgrounds/_search/`에 저장해 재사용
    - 배경 원본의 검은 띠는 cropdetect로 자동으로 잘라냄
    - 썰: 네이트판 등 남의 글 가져오기는 저작권·재사용 콘텐츠·약관 문제로 하지 않음 (사용자 동의). AI가 판 스타일로 새로 창작, 설명에 "재구성된 가상의 이야기" 자동 표기, 화자 성별에 따라 목소리 선택, 위쪽에 사연 제목 고정
    - 영상 하나: 잡지식 약 3분, 썰 약 3분, 랭킹 약 4~5분 (검색·다운로드 포함), 최대 메모리 약 430MB
  - 5단계: 채널 3개 (스타일 하나씩, 하루 2개씩, 이름은 가칭) — 사용자 결정 2026-10-05
    - `channels/japhak.yaml` 잡학 한입: trivia, InJoon +35%, 노랑, 음악 bright·mystery
    - `channels/ranklab.yaml` 순위 연구소: ranking, Hyunsu +35%, 하늘색, 음악 bright
    - `channels/ssul.yaml` 오늘의 썰: story, 화자별 SunHi/InJoon +30% 피치 -4Hz, 분홍, 음악 calm·mystery
    - 실행: `.venv/bin/python -m src.make_video --channel <ID> --topic "주제"` → `output/<ID>/<날짜>/`, 드라이브 `shorts-factory/<ID>/<날짜>/`
    - 영상 길이는 스타일이 정함 (잡지식 약 40초, 랭킹 약 50초, 썰 약 55초)
    - 주의: 채널끼리 같은 배경 풀을 같이 씀 → 업로드 시작 전 배경 차별화 필요 (보류 중)
  - 썰 채널 개편 (2026-10-05): 네이트판 등 남의 글을 퍼오거나 각색하는 기능은 만들지 않음 (사용자가 여러 번 요청했으나 저작권·채널 위험으로 거절, '소장용' 명목도 거절). 대신:
    - story(AI 창작 썰): "현실 공감형" 지침 (막장 금지, 흔한 일상 갈등, 생활 디테일, 열린 결말), Gemini Pro 모델 (`agy_model`)
    - case(판례 썰): 법제처 Open API로 생활 분쟁 판례 검색 → AI가 공감되는 사건 선택 → 당사자 1인칭 사연 + "판결" 공개. 판결문은 저작권법 제7조로 보호 대상 아님. 사실·금액은 판결문 그대로, 설명란에 사건번호 표기
    - 법제처 API 이용자 ID: .env `LAW_API_OC` (없으면 시험용 test). 사용자가 open.law.go.kr에서 본인 계정 신청 필요 (7단계 전)
    - 썰 채널 하루 2개 = story 1 + case 1
  - 6단계: `.venv/bin/python -m src.main` 한 번에 모든 채널 daily_count만큼 제작 (`--dry-run` 주제만, `--channel`, `--count`)
    - `src/db.py`: `data/history.db` videos 표 (uid, channel, style, topic, title, status, error, path, provider, case_id)
    - 영상 코드(uid, 예: ja-6d079f)는 업로드 정보 설명란에 들어감 → 사용자가 유튜브 설명에 같이 붙여 넣기 → 8단계 매칭용
    - `src/planner.py`: 채널 스타일을 번갈아 배정, AI 주제 후보 10개 (`templates/_topics.md` + style.yaml `topic_guide`), 핵심 단어 겹침(조사 제거)으로 중복 판정 (SIMILAR 0.65)
    - case는 판례를 영상 만들 때 자동 선택, 쓴 판례는 DB/`data/used_cases.json`에 기록
    - 실패한 영상은 기록 후 건너뜀. AuthExpired/DailyLimit이면 중단. 로그 `logs/<날짜>.log`
    - 금지 주제 글자 검사는 주제·제목만 (대본 본문은 '성인 남성' 같은 오판 → AI 검토에 맡김)
    - 6개 제작 약 15분 (영상당 3~5분), 하루 LLM 약 20회 예상 (agy 상한 40)
  - 7단계 (사용자 결정 2026-10-07): (처음엔 04:00·14:00 채널마다 1개씩 → 아래 '일정 변경'으로 바뀜) 하루 6개. 알림 없음. 서버 영상 14일 보관
    - 서버 시간대를 Asia/Seoul로 변경 (날짜 폴더·cron 시간이 한국 기준)
    - cron → `scripts/daily.sh` (flock으로 겹침 방지, PATH 설정) → `src.main --count 1 --cron` → 끝나고 `src.cleanup`
    - crontab 내용은 `scripts/crontab.txt`에 백업 (복구: `crontab scripts/crontab.txt`)
    - 알림 대신 드라이브 `shorts-factory/_상태.txt`에 실행 결과 기록 (최근 14번, 로그인 만료 시 안내 문구)
    - 스타일 배정: 최근 7일 동안 덜 만든 스타일부터 (하루 두 번 나눠 돌려도 썰 채널은 story/case 번갈아)
    - cleanup: 14일 지난 날짜 폴더는 드라이브에 다 있을 때만 삭제 (rclone check), `_work` 하루, logs 60일
    - 실행 기록: `logs/cron.log`, `logs/<날짜>.log`
    - 법제처 본인 계정은 다음에 (사용자 결정) → 그때까지 OC=test
  - 배경 결정 (2026-10-07): 잡학·랭킹 = 무료 실사 영상(현행), 썰 채널 = AI 장면 그림 + 움직임 효과 (추가 비용 0원)
    - `src/images.py`: Antigravity CLI 이미지 생성(Nano Banana, Google AI Pro 구독). `--mode accept-edits`(파일 편집만 허용, 명령 실행 금지)
    - agy는 그림을 `~/.gemini/antigravity-cli/brain/<대화ID>/sceneN_*.jpg`에 저장 → 찾아서 복사. 동영상 생성 기능은 없음 (NO_VIDEO_TOOL)
    - 구독 그림 한도: 하루 약 10장 남짓 (13장째 429 RESOURCE_EXHAUSTED) → 영상당 4장, `images.daily_limit: 10`
    - 대본 JSON에 characters(인물 외모, 영어)와 scenes 4개(from=대본 문장 앞부분, image=영어 장면 설명) → 장면 시작 시간은 from을 단어 타이밍에 맞춤
    - `background.make_from_images`: 확대·이동(Ken Burns) 4종 + xfade 전환. 그림이 절반 이상 실패하면 무료 영상 배경으로 대신
    - 채널 설정 `scene_images` (ssul만 켜짐), 설명란에 "장면 그림은 AI로 생성" 자동 표기
    - 판례 고르기: 키워드 8개까지 시도, "가장 나은 것 선택" 기준으로 완화
  - 일정 변경 (2026-10-07, 사용자 결정): 04:00 썰 채널 2개 (story 1 + case 1), 16:00 잡학 2개 + 랭킹 2개. 하루 6개 유지
    - 썰 채널 = 최우선 (`priority: 1`, 새벽에 구글 한도를 먼저 사용). `scene_images.required: true` → 그림을 못 그리면 무료 영상으로 대신하지 않고 "skipped"로 기록하고 건너뜀 (다음 실행에서 재시도)
    - 그림 한도 감지: 우리 상한(`images.daily_limit`) 또는 agy 기록의 429 RESOURCE_EXHAUSTED → 그날 남은 썰 영상은 대본 쓰기 전에 바로 건너뜀
    - `daily.sh`는 인자를 그대로 `src.main`에 넘김 (`--channel`, `--count`)
  - 그림 생성 방식 검토 (2026-10-07): 이 서버(2GB, GPU 없음)에서 직접 돌리기는 불가. 상시 GPU 서버(월 15만~100만 원)는 과함 → Antigravity 유지 (사용자 결정). 한도 부족 시 순서: Google AI 크레딧 소량 → 서버리스 GPU(월 약 5천~1만 원)
  - 배경음악 교체 (2026-10-08, 사용자 "음악이 별로"): 유튜브 오디오 보관함(직접 받기)은 사용자가 원치 않음. ccMixter는 자동 다운로드 차단(403), Openverse는 상업용 곡 거의 없음
    - Kevin MacLeod 전체 목록(incompetech pieces.json, 1,443곡)에서 장르·분위기·최근 곡 기준으로 채널별 10곡 새로 선곡: km_bright(잡학), km_energy(랭킹), km_calm(썰)
    - 드라이브 `test/music_preview/`에 채널별 미리듣기(곡마다 20초)와 곡 목록. 마음에 안 드는 곡은 sources.yaml에서 빼면 됨
  - 운영 방향 변경 (2026-10-08, 사용자 결정): 판례 채널(ssul, 오늘의 썰) 하나만 운영하고 발전시키기. 잡학·랭킹은 `active: false`로 중지 (16:00 cron 주석 처리). 다시 켜려면 active: true + crontab 주석 해제
  - 판례 대본 개편 (2026-10-08): 사용자 피드백 "AI 티, 성의 없음" → 대본 분석 (`data/research/`, git 제외)
    - 판례도서관(판례 채널, 100개, 중간값 1.1천 회) vs 신비한건축사전(70만 구독, 200개, 중간값 47만 회) vs 우리 대본을 수치 비교: 문장 길이, 끝맺음, 질문·숫자·과장 표현 밀도
    - case 스타일: 3인칭 해설, 짧은 문장, "~습니다"+"~죠/~거든요", 과장·"여러분" 금지, 질문은 반론 하나. 구조: 상황+반전 훅 → 시간순 전개 → 소송 → 반론 질문 → 판결(여기서 처음 공개) → 한계 → 첫 장면으로 마무리. 약 1분 50초
    - 1차 테스트 실패 피드백 "처음부터 무슨 상황인지 모르겠고 흥미 없음" → 원인: 결과부터 말하는 첫 문장, 숫자 과다, 그리고 AI 검토 단계가 훅을 지워 버림
    - 수정: 첫 두 문장 규칙(누가 무슨 일 + 반전, 결과 숨김), 숫자 핵심만, 검토가 첫 문장을 바꾸면 검토 결과 폐기 (`script._first_sentence`)
    - `style_checks` (style.yaml): AI 티 자동 검사 → 이후 Sonnet 방식으로 바뀌며 코드 삭제 (2026-10-12)
    - 테스트 채널 `channels/ssul_test.yaml` (active false, 그림 없이 무료 영상)
  - 판례 대본 자동 개선 (2026-10-09 새벽, 사용자 부재 중 9라운드): 보고서 `output/test/대본개선_보고서.txt` (드라이브 test/)
    - 핵심 변화: 검증된 사실 목록 단계 (`cases.fact_sheet`, `templates/case/facts.md`, 저장 `data/case_facts/`) → 대본은 목록으로만 작성 (`cases.writing_source`)
    - 판결문에서 주문(결과)·청구취지(요구)를 프로그램이 분리 표시. 대본 금액이 판결문 어디에도 없으면 다시 쓰기 (`script.money_problems`, 합계 허용)
    - 검사: 꼭 지킬 것(사실·금액·형식) vs 다듬기(문장 길이·용어·글자 수 10% 이내) 구분, 다듬기만 남으면 경고 후 통과 (`script._is_soft`)
    - 세는 말 앞 숫자 자동 변환 (`script.fix_counters`: 7개 → 일곱 개). 첫 문장 35자, 법률 용어 목록, 평가하는 말 금지
    - 검토 단계: 첫 문장(훅) 변경 금지, 사실·금액 문제가 없고 다듬기 문제가 늘지 않으면 검토 결과 채택
    - 판례 채널(ssul): styles [case]만, 장면 그림 5장. 길이 380~500자 (약 1분 15초)
    - 실험 도구: `output/_work/iter.py`(고정 판례 4건), `iter_new.py`(새 판례), `render_json.py`(대본 JSON → 테스트 영상)
    - 사실 대조 교훈: 내가 오류라고 의심한 것 중 2건은 실제로 AI가 맞았음 (1심+2심 합계, 건강/고령 이유 구분) → 의심되면 판결문 원문 확인 후 판단
  - 대본 방식 확정 (2026-10-09, 사용자 결정): 다른 AI 평가자 = Antigravity의 Claude Sonnet 5.5 (`claude-sonnet-5-5-medium`). GPT-OSS 120B는 평가가 일반적이고 사실 오류가 많아 탈락
    - 원칙: 평가자에게는 최소 정보만 ("유튜브 쇼츠 대본이야" + 대본). 우리 지침·기준표·판결문은 주지 않음
    - 흐름 (`src/polish.py`): Gemini 초안(가벼운 지침, 사실 목록만) → Sonnet 평가 → Sonnet 고쳐 쓰기(대본+평가만) → 재평가, 큰 문제 남으면 1번 더 → 사실 확인(Gemini, 사실만 수정, 판결 구간 나누기, 장면 위치) → Sonnet 제목·화면 제목 → 금액 검사·숫자 변환·안내 꼬리말 제거
    - 기존 숫자 기반 말투 규칙(style_checks)과 기존 검토 단계는 제거 (부자연스러움의 원인). `templates/_evaluate.md`, `_rewrite.md`, `_title.md`, `case/factfix.md`
    - `llm.generate(providers=["agy"])`: 평가자 호출이 실패해도 다른 AI로 몰래 넘어가지 않게
    - 판례 고르기: 프로그램이 먼저 거름 (`cases.clear_result`: 환송·이송 제외, 주문에 금액이 있거나 기각인 사건만). 대본보다 사건 선택이 품질에 더 큰 영향
    - 그림 지시에 로고·상표·간판 글자 금지 추가 (렌터카 매장에 실제 자동차 브랜드 로고가 그려졌던 일)
    - 사용자 평가: Sonnet 방식 대본 "전보다 훨씬 좋음, 나쁘지 않은 수준". 자동 제작은 대기 (사용자 지시)
    - Antigravity 하루 상한 60회 (판례 영상 1개에 약 12~15회)
  - 표기 정리 단계 (2026-10-09): 대본 쓰기·다듬기에는 표기 규칙을 주지 않고, 마지막에 `polish.notation`(`templates/_notation.md`)으로 표기만 정리
    - 한글로 풀어 쓴 숫자 → 아라비아 숫자 (1988년 12월, 4억 8천만 원), 소리 나는 대로 쓴 영어 → 원래 표기 (BMW). 세는 말 앞 작은 수는 한글 (fix_counters)
    - 길이가 크게 달라지면(내용 변경 의심) 정리 결과를 버림. edge-tts는 "1988년", "BMW"를 정상적으로 읽음
    - 마무리의 시청자 당부·댓글 유도·위로 문장은 사실 확인 단계 + `polish.strip_viewer_tail`로 제거 (사용자 결정: 없는 게 좋음)
    - 판례는 지방법원 사건만 (`cases.clear_result`), 길이는 크게 신경 쓰지 않음 (300~700자, 길이 문제는 다듬기로만)
    - 드라이브는 2026-10-09에 전부 비움 (사용자 요청). 테스트 영상은 ssul_test 폴더
  - 대본 직접 수정 → 영상 다시 만들기 (2026-10-09, 사용자 선택 "1번 방식"): `src/edits.py`
    - 영상을 만들 때 재료를 `output/<채널>/<날짜>/<번호>_project/`에 보관 (project.json: 구간 대본·화면 제목·스타일·채널·화자·배경 풀·seed·장면·음악, 장면 그림 파일)
    - 드라이브에 `<번호>_대본` 구글 문서 업로드 (rclone `--drive-import-formats txt --drive-export-formats txt`, 앱이 만든 파일이라 drive.file 권한으로 읽기 가능, 수정해도 같은 파일 ID)
    - cron 15분마다 `scripts/edits.sh` → `src.edits check`: 문서 내용 해시가 바뀐 영상만 다시 만듦 (목소리·자막 자동, 그림·음악·배경 seed 재사용, 업로드 정보 [대본]·[화면 위 제목] 갱신, 드라이브 영상 교체). 같은 잠금 파일이라 제작 중이면 건너뜀
    - 재료 폴더는 드라이브에 올리지 않음 (export·cleanup에서 `*_project/**` 제외). 영상 하나 다시 만드는 데 약 4~5분
  - Google Flow 장면 영상 (2026-10-10, 사용자 결정 C안·B안): 판례 영상 하루 1개, 장면 6개 × Flow 10초 (Omni 1.1 Flash, 15크레딧씩 = 하루 90). 일요일 + 한 달에 2~3일 쉬기. Flow는 API가 없어 사용자가 직접 만듦 (자동 조작 안 함)
    - 대본 JSON scenes 6개: from + image(시작 그림) + motion(10초 움직임). 서버가 시작 그림(웹툰풍)을 그림
    - 영상을 만들면 드라이브 날짜 폴더에 `<번호>_flow/`(시작그림_1~6)와 `<번호>_Flow작업` 문서(장면별 Flow 문장 = motion + 채널 flow.style_suffix, 설정) 업로드 (`edits.upload_flow_work`)
    - 사용자가 Flow 영상을 `<번호>_flow/`에 `장면N` 이름으로 넣으면, 15분마다 `edits.check`가 받아서(`fetch_flow_clips`, 파일 ID·크기·시간으로 변경 감지) 그 장면만 영상으로 바꿔 다시 만듦. 짧으면 최대 1.35배 느리게 + 마지막 화면 정지 (`background._clip_part`)
    - 설명란: "장면 영상은 AI(Google Flow)로 생성" 자동 표기
    - 시험 통과 (2026-10-12, 6장면 교체 확인. Flow 워터마크 ✦는 지우지 않고 그대로 사용 — 사용자 결정)
    - 쉬는 날: config.yaml `schedule.off_days` (일요일은 cron `1-6`). `_상태.txt`에 Flow 남은 장면 표시 (`main.flow_todo`)
  - 2026-10-13 장애 2건:
    - edge-tts 403 (마이크로소프트가 10-10에 접속 방식 변경, 전 세계 공통) → 판례 채널 목소리를 **Supertonic M1**로 교체 (사용자 선택). 서버 안에서 직접 생성(가입·인터넷 불필요, 모델 OpenRAIL-M 상업 사용 가능), 메모리 약 650MB, 모델 읽기 약 30초. 채널 voices에 `supertonic:M1`, 속도 `+25%` → 1.25배. 단어 타이밍은 문장별 생성 + 문장 안 글자 수 비율 (`tts._supertonic_synthesize`)
    - Antigravity에서 Gemini 3.1 Pro가 빠짐 → 작가 모델 `gemini-3.8-flash-high`. 모델이 없어지면 Claude로 넘어가지 않고 agy 기본 모델로 다시 시도 (`llm._call_agy`)
    - 자동 제작(main)에서 대본 문서·Flow 작업 폴더가 드라이브에 안 올라가던 문제 수정 (`edits.publish`)
  - 2026-10-17:
    - 04:00에 edits.sh가 잠금을 먼저 잡으면 daily.sh가 조용히 건너뛰던 문제 (10-14, 10-17 영상 빠짐) → daily.sh는 잠금을 최대 1시간 기다림 (`flock -w 3600`)
    - Flow 장면이 들어가 다시 만든 영상은 드라이브에 `<제목>.mp4`로 올림 (사용자 결정). 서버 쪽은 `001.mp4` 그대로 (`export.drive_names`, cleanup도 반영)
  - 2026-10-28: agy가 그림을 일부만 그리고 끝내는 경우 (10-20: 4/6장) → 빠진 장면만 한 번 더 그림 (`images.generate` retry)
