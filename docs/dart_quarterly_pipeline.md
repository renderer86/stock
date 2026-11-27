# 전 종목 분기 재무제표 수집

기존 `crawler_dart_financial_interim.py`가 분기 ZIP을 먼저 읽고 부족한 기업만
OpenDART 전체 재무제표 API로 보완한다. 연간 10년 패널은 기존
`crawler_dart_financial_bulk.py`로 관리하며, 분기 데이터는 연간 관측치에 섞지 않는다.

## 수집 순서와 분할 기준

1. 최신 제출기한이 지난 1분기·반기·3분기를 정한다. 연도와 분기를 지정할 수도 있다.
2. 해당 분기의 재무상태표·손익계산서·현금흐름표·자본변동표 ZIP 4개를 받는다.
3. 원본의 헤더와 행을 연결/별도·종목코드 첫 자리별 gzip JSON으로 저장한다.
   파일명이 같으면 저장된 원본을 재사용한다. 정정 등으로 ZIP 파일명이 바뀌면 재수입한다.
4. 당기/전년 동기 누적액을 구분해 계산용 데이터를 만든다. 같은 기업의 연결과
   별도 금액을 합치지 않으며, 결산기준일·보고서 종류·통화도 확인한다.
5. 재무상태표·손익계산서·현금흐름표 또는 필요한 표준 계정/현금흐름 비교액이
   빠진 기업만 API 대기열에 넣는다. 금융업은 비금융업 FCF 요건을 적용하지 않는다.
6. API는 기본 실행당 최대 500개 기업, 전체 HTTP 요청 1,000회, 실행시간 15분으로
   제한한다. 먼저 도달한 한도에서 저장하고 멈춘다. 기업별 API 호출은 순차 실행한다.

ZIP은 4개 파일로 전 종목을 함께 처리하므로 기업 500개 제한을 적용하지 않는다.
파일 다운로드는 하나씩 진행하고 각 파일 처리 후 체크포인트를 남긴다.
API는 보완 대상만 나눠 처리한다. 같은 명령을 다시 실행하면 미수집 기업,
재시도 시점이 된 실패 기업, 재확인 시점이 된 API 성공 기업 순서로 진행한다.
ZIP으로 충분한 기업은 API를 호출하지 않는다.

## 실행 예시

```powershell
# 로컬 상태 확인: 네트워크 요청과 파일 변경 없음
python crawler_dart_financial_interim.py --status

# 먼저 ZIP만 받아 전 종목 자료 반영 및 누락 대상 계산 (인증키 없이도 가능)
python crawler_dart_financial_interim.py --year 2026 --quarter 3 --bulk-only

# ZIP 확인 후 누락 기업을 최대 500개씩 보완. 같은 명령으로 이어받기
python crawler_dart_financial_interim.py --year 2026 --quarter 3

# 저장된 ZIP 반영 결과에서 API 보완만 재개
python crawler_dart_financial_interim.py --year 2026 --quarter 3 --bulk-mode skip --max-companies 100 --max-requests 250

# 특정 종목만 수집하거나 반기 자료를 별도로 보관
python crawler_dart_financial_interim.py --year 2026 --quarter 2 --codes 005930,000660

# 과거 분기 ZIP을 기간별 파일로 반영하고 최신 3분기 파일은 유지
python crawler_dart_financial_interim.py --year 2026 --quarter 1 --bulk-only --output data/dart_financial_interim_2026_q1.json
python crawler_dart_financial_interim.py --year 2026 --quarter 2 --bulk-only --output data/dart_financial_interim_2026_h1.json

# API 보완이 끝난 데이터로 화면 재계산
python build_investment_screens.py
python build_data_manifest.py
```

명시한 기간의 체크포인트는 기간별로 보관한다. 과거 분기를 수집해도
`dart_financial_interim.json`의 더 최신 분기 값을 덮어쓰지 않는다.
`--status`의 수치는 새 ZIP을 받기 전 로컬 상태이므로 실제 ZIP 반영 후 대기열과 다를 수 있다.

`--max-companies 0`은 기업 수 제한만 해제한다. 호출 수와 시간 제한은 계속 적용된다.
네트워크 요청에는 남은 시간을 반영한 타임아웃을 사용하며, 이미 진행 중인 ZIP 해석·저장은
완료한 뒤 중단한다. 체크포인트는 API 기업 25개마다, 분기 ZIP 1개마다, 정상 종료와
Ctrl+C 중단 시 저장한다. 한도 초과 직전 연결 조회만 끝났다면 다음 실행에서 별도 조회부터
이어간다. API 인증/요청 제한/점검 응답에서는 추가 기업 조회를 멈춘다.

## 재조회와 수집 대상

- API 성공 자료는 기본 7일간 재사용한다. `--refresh-days`로 조정한다.
- 조회 결과 없음(`013`)과 오류는 기본 24시간 후 재시도한다.
  `--retry-failed`는 이 대기시간만 무시한다. `--force`는 API 성공 자료의 대기시간도 무시한다.
- ZIP 단계가 실패하면 저장된 원본을 보존하고 API 단계로 넘어가지 않는다.
- 시장 종목 목록과 DART 기업 고유번호를 연결해 전 종목을 선정한다. ETF 등
  재무제표를 조회할 기업이 없는 항목은 별도로 집계한다.
- API 보완 모드에서는 기업 고유번호 캐시가 없거나 7일 이상 지나면 새로 받아
  신규 상장사를 포함한다. `--refresh-corp-codes`로 갱신을 요청할 수도 있다.
- `--scope watchlist`는 기존 관심종목 중심 수집에 사용할 수 있다.
- `DART_API_KEY`가 없으면 ZIP 단계 결과를 저장하고 API 보완은 건너뛴다.

## 저장 구조와 자동 실행

- `data/dart_financial_interim.json`: 최신 계산용 기업별 재무·현금흐름과 수집 범위
- `data/dart_financial_interim_2026_q1.json`, `data/dart_financial_interim_2026_h1.json`: 2026년 1분기·반기 ZIP 계산용 자료. 부족한 계정은 기간별 진행 파일에서 확인한다.
- `data/dart_financial_interim_progress/{연도}_{보고서코드}.json`: 기간별 상태·누락 사유·마지막 실행 한도
- `data/dart_financial_raw/{연도}/bulk/{보고서코드}_{BS|PL|CF|CE}_{CFS|OFS}_{첫자리}.json.gz`: 분기 ZIP 원본
- `data/dart_financial_raw/{연도}/api/interim_{보고서코드}_{CFS|OFS}_{첫자리}.json.gz`: API 원본
- `data/dart_corp_codes.json`: 신규 상장사를 포함한 고유번호 캐시

기존 GitHub Actions `Refresh Buffett and quality screens`에서 자동으로 ZIP 우선 수집과
API 한 묶음을 실행한다. 수동 실행에서는 `bulk_mode=only`로 ZIP만 먼저 반영하고
`auto` 또는 `skip`으로 API 보완을 이어갈 수 있다. 수집 결과와 원본, 체크포인트는 함께
커밋하도록 구성되어 다음 실행에서도 진행 상황을 유지한다. 변경한 워크플로를 저장소에
반영한 이후 적용된다.
연간 패널 수집과 분기 갱신은 같은 동시 실행 그룹을 사용해 원본 인덱스를 동시에
덮어쓰지 않도록 순차 실행한다.

원본은 가공하지 않는다. 정규화할 수 없는 계정과 없는 값은 미확인으로 남기며
금액을 0으로 추정하지 않는다. API도 같은 항목을 제공하지 않는 경우에는 재무계산에서
계속 결측으로 취급한다.
외화 공시 원본도 보관하지만 `unsupported_currency`로 표시하고 KRW 계산에 사용하지 않는다.
