아래 실제 판결로 유튜브 쇼츠 대본 초안을 써 줘. 대본은 TTS가 읽는다. 판결 결과는 끝부분에서 공개한다.

# 실제 판결 (검증된 사실 목록)
{source_text}

# 지켜야 할 것
- 사실은 사실 목록에 있는 것만. 지어내지 않는다. 날짜·금액·이유를 바꿔 말하지 않는다.
- 이름, 주소, 아파트·회사 이름 같은 개인 정보 금지.
- TTS용: 괄호, 이모지, 영어 약어, 특수기호 금지.
- 길이: 공백 제외 {min_chars}~{max_chars}자.

# 금지 주제
{banned_topics} 에 해당하면 segments를 빈 목록으로 둔다.

# 출력 형식
JSON 하나만. 설명, 마크다운, 코드블록 없이.
{{
  "title": "유튜브 제목 (35자 이내)",
  "header": "화면 위에 띄울 사건 제목 (24자 이내)",
  "narrator": "male",
  "segments": [
    {{"label": "", "text": "판결 결과 앞부분"}},
    {{"label": "판결", "item": "판결 한 줄 요약 (16자 이내)", "text": "판결 결과부터 끝까지"}}
  ],
  "description": "영상 설명 2문장",
  "hashtags": ["#쇼츠", "#판례", "주제 관련 태그 2~3개"],
  "background_pool": "다음 중 하나: {background_pools}",
  "music_pool": "다음 중 하나: {music_pools}",
  "fact_check": ["판결 결과와 금액, 날짜, 사건번호 등 업로드 전 확인할 것"],
  "characters": "주요 인물 외모 (영어, 장면 그림용)",
  "scenes": [{{"from": "장면이 시작되는 대본 문장 앞부분 (대본 글자 그대로)", "image": "English scene description, no text in image"}}]
}}
scenes는 대본 흐름대로 5개.
