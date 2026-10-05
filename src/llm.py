"""LLM CLI 호출 래퍼: Antigravity(agy) → 실패하면 Claude Code(claude)로 자동 전환.

- 하루 호출 상한, 호출 간격, 재시도
- 로그인 만료 감지 (AuthExpired)
- AI가 프로젝트 파일을 건드리지 못하게 빈 폴더(data/llm_sandbox)에서 실행

단독 실행:
    .venv/bin/python -m src.llm "한 문장으로 인사해줘"
    SHORTS_LLM_FORCE_FAIL=agy .venv/bin/python -m src.llm "인사해줘"   # agy 실패 → claude 전환 테스트
"""
import argparse
import datetime as dt
import json
import logging
import os
import subprocess
import time

from src import config

log = logging.getLogger("llm")

AUTH_PATTERNS = (
    "not logged into", "not signed in", "currently not signed in", "please run /login",
    "invalid api key", "oauth token has expired", "authentication_error", "unauthenticated",
    "login required",
)


class LLMError(RuntimeError):
    pass


class AuthExpired(LLMError):
    """로그인 만료. 사용자가 다시 로그인해야 한다."""


class DailyLimit(LLMError):
    pass


def _cfg() -> dict:
    return config.load()["llm"]


# ---------- 사용량 기록 (하루 상한, 호출 간격) ----------

def _usage_file():
    return config.path(_cfg()["usage_file"])


def _load_usage() -> dict:
    f = _usage_file()
    return json.loads(f.read_text()) if f.exists() else {}


def _record_call(provider: str) -> None:
    usage = _load_usage()
    today = dt.date.today().isoformat()
    usage = {today: usage.get(today, {})}  # 오늘 것만 남김
    usage[today][provider] = usage[today].get(provider, 0) + 1
    usage["last_call"] = time.time()
    f = _usage_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(usage, indent=1))


def calls_today(provider: str) -> int:
    return _load_usage().get(dt.date.today().isoformat(), {}).get(provider, 0)


def _wait_interval() -> None:
    last = _load_usage().get("last_call", 0)
    wait = _cfg()["min_interval_sec"] - (time.time() - last)
    if wait > 0:
        time.sleep(wait)


# ---------- 프로그램별 호출 ----------

def _run(cmd: list[str], provider: str) -> subprocess.CompletedProcess:
    sandbox = config.path(_cfg()["sandbox"])
    sandbox.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, cwd=sandbox, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=_cfg()["timeout_sec"])
    except subprocess.TimeoutExpired:
        # agy는 로그인이 풀리면 브라우저 로그인을 기다리며 멈춘다 → 시간 초과도 로그인 문제일 수 있음
        raise LLMError(f"{provider}: {_cfg()['timeout_sec']}초 안에 응답 없음 (로그인 만료일 수도 있음)")
    text = (proc.stdout + proc.stderr).lower()
    if any(p in text for p in AUTH_PATTERNS):
        raise AuthExpired(f"{provider}: 로그인이 만료되었습니다. 다시 로그인해 주세요.")
    if proc.returncode != 0:
        raise LLMError(f"{provider}: 종료 코드 {proc.returncode}: {proc.stderr.strip()[-300:]}")
    return proc


# agy는 에이전트라서 글자 수를 세려고 명령을 실행하려다 막히면 빈 답을 낸다 → 도구 사용 금지를 명시
AGY_PREFIX = ("[지시] 어떤 도구도 쓰지 말고 명령도 실행하지 마. 파일을 만들거나 읽지도 마. "
              "글자 수 같은 건 머릿속으로 어림해. 아래 요청에 대한 최종 답변 텍스트만 바로 출력해.\n\n")


def _call_agy(prompt: str, model: str | None = None) -> str:
    cmd = [config.tool("agy"), "-p", AGY_PREFIX + prompt, "--output-format", "json",
           "--print-timeout", f"{_cfg()['timeout_sec'] - 10}s"]
    model = model or _cfg().get("agy_model")
    if model:
        cmd += ["--model", model]
    out = json.loads(_run(cmd, "agy").stdout)
    if out.get("status") != "SUCCESS" or not out.get("response"):
        denied = [a.get("display_name") for a in out.get("denied_actions", [])]
        raise LLMError(f"agy: 빈 응답 (상태 {out.get('status')}, 막힌 동작 {denied})")
    return out["response"]


def _call_claude(prompt: str, model: str | None = None) -> str:
    cmd = [config.tool("claude"), "-p", prompt, "--output-format", "json", "--tools", "",
           "--no-session-persistence"]
    if _cfg().get("claude_model"):
        cmd += ["--model", _cfg()["claude_model"]]
    out = json.loads(_run(cmd, "claude").stdout)
    if out.get("is_error") or not out.get("result"):
        raise LLMError(f"claude: 실패 응답 {str(out)[:300]}")
    return out["result"]


CALLERS = {"agy": _call_agy, "claude": _call_claude}


def generate(prompt: str, agy_model: str | None = None) -> tuple[str, str]:
    """프롬프트 → (답변 텍스트, 사용한 프로그램). 순서대로 시도하고 전부 실패하면 오류.
    agy_model: 이번 호출만 다른 Antigravity 모델 사용 (예: 창작은 Pro)"""
    cfg = _cfg()
    errors, auth_errors = [], []
    for provider in cfg["providers"]:
        if calls_today(provider) >= cfg["daily_limit"][provider]:
            errors.append(f"{provider}: 오늘 호출 상한({cfg['daily_limit'][provider]}회) 도달")
            continue
        for attempt in range(1, cfg["retries"] + 1):
            _wait_interval()
            _record_call(provider)
            try:
                if os.environ.get("SHORTS_LLM_FORCE_FAIL") == provider:  # 전환 테스트용
                    raise LLMError(f"{provider}: 테스트용 강제 실패")
                text = CALLERS[provider](prompt, agy_model if provider == "agy" else None)
                log.info("%s 응답 성공 (시도 %d)", provider, attempt)
                return text, provider
            except AuthExpired as e:
                log.error(str(e))
                auth_errors.append(str(e))
                break  # 로그인 문제는 재시도해도 소용없음 → 다음 프로그램으로
            except LLMError as e:
                log.warning("%s 시도 %d 실패: %s", provider, attempt, e)
                errors.append(str(e))
        log.warning("%s 포기 → 다음으로 전환", provider)
    if auth_errors and len(auth_errors) == len(cfg["providers"]):
        raise AuthExpired(" / ".join(auth_errors))
    if errors and all("상한" in e for e in errors):
        raise DailyLimit(" / ".join(errors))
    raise LLMError("모든 LLM 호출 실패: " + " / ".join(auth_errors + errors))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="LLM 호출 테스트")
    ap.add_argument("prompt")
    args = ap.parse_args()
    text, provider = generate(args.prompt)
    print(f"[{provider}]\n{text}")


if __name__ == "__main__":
    main()
