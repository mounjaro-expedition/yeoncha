# 연차하루면 충분행 — MVP

한국 공휴일 기준 **연차 0~1일로 갈 수 있는 해외여행 날짜**를 자동 계산하고,
그 날짜의 왕복 항공권이 평소보다 싸면 텔레그램 채널로 알려주는 봇입니다.

## 구조
```
main.py                 실행 진입점
config.yaml             출발지·목적지·특가 기준 설정
data/holidays_kr.json   공휴일 데이터 (2026.12 ~ 2027.12)
yeoncha/calendar_kr.py  연차 1일 연휴 구간 계산
yeoncha/flights.py      Travelpayouts 가격 수집 + 목업
yeoncha/store.py        가격 이력 SQLite 저장
yeoncha/deals.py        특가 판정 (평소가 대비 / 날짜별 하락 / 목표가)
yeoncha/notify.py       텔레그램 메시지 작성·발송
yeoncha/site.py         특가 웹페이지 생성 (docs/index.html)
yeoncha/site_template.html  웹페이지 디자인
.github/workflows/      매일 09:00 자동 실행
```

## 1. 로컬에서 먼저 테스트 (토큰 불필요)
```bash
pip install -r requirements.txt
python main.py windows --boosted          # 공휴일 낀 꿀연휴만 보기
python main.py run --mock --dry-run       # 가짜 가격으로 전체 흐름 확인
```
실행 후 `docs/index.html`을 더블클릭하면 브라우저에서 특가 사이트를 미리 볼 수 있어요.
`--mock`은 화면 확인용 **가짜 가격**이라 실제 가격과 달라요 (사이트 상단에 노란 안내가 떠요).

## 2. 계정 준비
1. **Travelpayouts** 가입 → Aviasales 프로그램 연결 → 대시보드에서 API 토큰과 마커(marker) 확인
2. **텔레그램**: @BotFather에서 봇 생성 → 토큰 받기 → 공개 채널 만들고 봇을 관리자로 추가
   → `TELEGRAM_CHAT_ID`는 `@채널아이디` 형식
3. 실데이터 첫 테스트:
   ```bash
   export TP_TOKEN=... TP_MARKER=...
   python main.py run --dry-run
   ```
   서울 출발 노선의 데이터가 충분히 잡히는지 먼저 확인하세요.

## 3. 자동화 (GitHub Actions)
1. 이 폴더를 **비공개** GitHub 저장소로 올리기
2. Settings → Secrets and variables → Actions에 4개 등록:
   `TP_TOKEN`, `TP_MARKER`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. Actions 탭 → daily-deals → Run workflow로 수동 실행해서 확인
4. 이후 매일 09:00(KST) 자동 실행, 가격 이력은 `data/prices.db`로 커밋되어 쌓임

## 4. 특가 사이트 공개 (GitHub Pages, 무료)
1. 저장소 Settings → Pages → Source를 "Deploy from a branch", 브랜치 `main`, 폴더 `/docs`로 지정
2. 몇 분 뒤 `https://아이디.github.io/저장소이름/` 주소로 공개됨
3. `config.yaml`의 `site.url`, `site.telegram_url`을 채우면 구독 버튼이 채널로 연결됨
4. 매일 자동 실행 때 사이트도 함께 갱신됨

참고: 무료 계정은 **공개 저장소에서만** Pages를 쓸 수 있어요. 토큰은 Secrets에 있어 공개해도 안전하고,
가격 이력 DB만 공개돼요. 저장소를 비공개로 두고 싶으면 Cloudflare Pages(무료)에 저장소를 연결해 `docs` 폴더를 배포하면 돼요.

## 연휴별 오늘의 최저가
- 공휴일 낀 '연차 하루' 연휴 중 가까운 12개(`config.yaml`의 `lowest.max_windows`)에 대해
  목적지별 직항 왕복 최저가를 날짜 지정으로 조회해 사이트에 보여줘요. 특가가 없는 날에도 사이트가 비지 않아요.

## 현지 체류 시간과 밤도깨비
- 가는 편 출발 시각 + 비행시간으로 현지 도착 시각을 구하고, 귀국편 출발까지를 **현지 체류 시간**으로 보여줘요 (시차 반영).
- 체류가 (박수×24시간)의 65% 미만이면 **밤도깨비** 일정으로 분류해요 (`config.yaml`의 `stay.short_ratio`).
  사이트에선 필터로, 텔레그램에선 별도 묶음으로 나와요.
- 귀국편이 날짜를 넘겨 도착하면 "연휴 다음 날 새벽 도착" 경고를 붙여요.

## 수하물 안내 (`data/airlines.json`)
- 가격 데이터에는 수하물 정보가 없어서, 항공사의 **가장 싼 운임 규정**과 **지역별 사전구매 요금표**로 추정해요.
  - 대형항공사(FSC)와 진에어: "위탁수하물 포함"
  - 그 외 LCC: "미포함일 수 있음" + 15kg 왕복 추가 추정액 (편도 사전구매 요금 × 2)
- 지역(`regions`): 일본(JP) / 중국(CN) / 홍콩·대만(HKTW) / 동남아(SEA). 새 목적지를 추가하면 지역에도 넣어주세요.
- 추정액이 하나라도 있으면 사이트에 **"짐 부치는 여행 기준으로 보기"** 토글이 켜지고, 수하물 포함 가격으로 다시 정렬돼요.
  요금을 모르는 항공사는 "수하물 요금 미확인"으로 표시돼요.
- 요금은 자주 바뀌니 `checked` 날짜를 갱신하며 분기마다 점검하세요. `_note`에 출처와 추정 여부를 적어뒀어요.

## 특가 판정 방식
- **직항만** 조회해요 (`config.yaml`의 `direct_only`). 연차 하루 여행에 경유는 의미가 없어서요.
- 특가 후보는 발송 직전 **그 날짜로 한 번 더 조회**해서, 5% 넘게 올랐거나 사라졌으면 제외해요.
- **평소가 대비**: 같은 노선·박수의 최근 60일 중앙값보다 25% 이상 저렴
- **이 날짜 하락**: 같은 출국·귀국일 과거 가격보다 20% 이상 하락 (연휴 날짜는 원래 비싸서 이 신호가 중요)
- **목표가**: 이력이 쌓이기 전 초기 2~3주는 `config.yaml`의 cap 이하이면 특가
- 이미 보낸 특가는 5% 더 떨어져야 텔레그램 재알림 (사이트에는 유효한 특가를 계속 노출)

## 출시 전 체크리스트
- [ ] `holidays_kr.json`을 공공데이터포털 '특일 정보' API로 교차 검증 (임시공휴일 추가 시 수동 반영)
- [ ] Travelpayouts 링크 생성기로 제휴 링크 형식·추적 여부 확인 (`flights.build_link`)
- [ ] 연결되는 예약 페이지가 한국 사용자에게 자연스러운지 확인 (필요 시 다른 제휴사로 교체)
- [ ] Data API는 캐시 가격 → 알림 문구에 변동 가능성 고지 (기본 포함됨)
- [ ] 제휴 수수료 고지 문구 유지 (기본 포함됨)
- [ ] `config.yaml`의 목적지·cap 값을 실제 가격 보면서 조정
