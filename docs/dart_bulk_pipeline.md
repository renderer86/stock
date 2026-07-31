# DART 10년 재무 수집 운영

`Build DART 10-year financial panel`은 OpenDART 재무정보 일괄다운로드 ZIP을
기본 데이터로 사용한다. 기업·연도별 `fnlttSinglAcntAll` 호출은 ZIP에서 찾지
못한 기업의 보완 용도로만 남겨 둔다.

## 최초 구축

GitHub Actions에서 다음 값으로 수동 실행한다.

- `scope`: `bulk-and-supplements`
- `mode`: `resume`
- `years`: `10`
- `universe_limit`: `0`
- `detail_request_budget`: `5000`

수집 순서는 핵심 패널 갱신, 2016~2025 사업보고서 BS·PL·CF·CE ZIP 가져오기,
원본 계정 행 저장, API 누락 보완, N 추정, 버핏·퀄리티 화면 생성 순이다.
ZIP 컨테이너 자체는 메모리에서만 사용하지만, ZIP 안의 TXT 헤더와 모든 행은
CFS/OFS를 구분한 gzip JSON 조각으로 저장소와 Action artifact에 보관한다.

## 이후 갱신

- 새 사업보고서 연도 반영: `bulk-and-supplements` + `refresh-latest`
- 주식 수·배당 API 보완 재개: `supplements-only` + `resume`
- ZIP만 다시 확인: `bulk-only` + `resume`
- 기존 기업별 전체 API 방식이 꼭 필요할 때만: `legacy-api-details`

`resume`에서는 OpenDART 목록의 ZIP 파일명이 기존 지문과 같고 해당 연도의
상세 데이터와 원본 조각 참조가 모두 있으면 다운로드를 건너뛴다. 예전 형식의
패널처럼 계산 결과만 있고 원본 참조가 없으면 같은 ZIP을 다시 읽어 원본 조각을
만든다.

## 저장 구조

- `data/dart_financial_panel.json`: 메타데이터와 샤드 목록
- `data/dart_financial_panel/2016.json` … `2025.json`: 연도별 관측치
- `data/dart_financial_raw/index.json`: 원본 조각 목록, 행 수, 크기, SHA-256
- `data/dart_financial_raw/{연도}/bulk/*.json.gz`: ZIP TXT의 원본 헤더·행 전체
- `data/dart_financial_raw/{연도}/api/*.json.gz`: 보완 API의 응답 행 전체
- `data/financial_n_estimates.json`: N 엔진 결과
- `data/investment_screens.json`: 버핏·퀄리티 화면 결과

분석 코드는 `dart_financial_storage.load_financial_panel()`을 사용하므로 기존
단일 JSON과 연도별 샤드를 모두 읽을 수 있다. 기존 단일 JSON은 다음 수동
Action에서 자동으로 샤드 형식으로 변환된다.

원본 파일은 연도·출처·재무제표·CFS/OFS·종목코드 첫 자리 기준으로 나뉜다.
따라서 GitHub의 파일당 100MB 제한을 피하면서도, 원본 헤더와 행 배열을 그대로
읽어 다른 방식으로 재가공할 수 있다. 각 패널 행의 `raw_financial_statements`,
`detail_api_raw_refs`, `share_raw_ref`, `dividend_raw_ref`가 해당 원본 조각을
가리킨다. 대시보드 배포물에서는 대용량 원본과 패널을 제외하되 Git 저장소와
수동 Action artifact에는 남긴다.

## 원본과 계산값의 관계

- 원본 계정 행은 정규화하거나 다른 값으로 덮어쓰지 않는다.
- 계산용 `detail_accounts`는 원본과 별도로 만든 표준 계정 사전이다.
- 계산 기준은 완전한 CFS를 우선하고, 없으면 완전한 OFS를 사용한다.
- 하나의 기업·연도 계산에서 CFS와 OFS의 계정 값을 섞지 않는다.
- 벌크와 API 값이 겹치면서 다르면 `detail_validation`에 두 값을 모두 남긴다.
- 벌크에 기업·연도 자료가 없거나 불완전한 경우에만 전체 재무 API를 사용한다.

## API 보완 범위

`screens` 프로필은 호출량을 줄이기 위해 다음 연도만 보완한다.

- 발행주식 수: 기업별 최초 연도, 최신 전년도, 최신 연도
- 배당 주요사항: 최신 3개 연도
- 전체 재무 API: ZIP에서 상세 재무를 찾지 못한 기업·연도

현금흐름표에 있는 배당 지급과 자사주 취득은 모든 연도에 걸쳐 ZIP에서
계산된다. 정확한 주당배당금이 10년 전체에 필요한 별도 연구에서는
`legacy-api-details`를 사용한다. API 보완 응답 역시 가공 전 행 전체가 원본
조각에 보존된다.
