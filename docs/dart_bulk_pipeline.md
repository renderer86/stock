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

수집 순서는 핵심 패널 갱신, 2016~2025 사업보고서 BS·PL·CF ZIP 가져오기,
API 누락 보완, N 추정, 버핏·퀄리티 화면 생성 순이다. ZIP은 메모리에서만
사용하고 저장소나 Action artifact에 보관하지 않는다.

## 이후 갱신

- 새 사업보고서 연도 반영: `bulk-and-supplements` + `refresh-latest`
- 주식 수·배당 API 보완 재개: `supplements-only` + `resume`
- ZIP만 다시 확인: `bulk-only` + `resume`
- 기존 기업별 전체 API 방식이 꼭 필요할 때만: `legacy-api-details`

`resume`에서는 OpenDART 목록의 ZIP 파일명이 기존 지문과 같고 해당 연도의
상세 데이터가 이미 있으면 다운로드를 건너뛴다.

## 저장 구조

- `data/dart_financial_panel.json`: 메타데이터와 샤드 목록
- `data/dart_financial_panel/2016.json` … `2025.json`: 연도별 관측치
- `data/financial_n_estimates.json`: N 엔진 결과
- `data/investment_screens.json`: 버핏·퀄리티 화면 결과

분석 코드는 `dart_financial_storage.load_financial_panel()`을 사용하므로 기존
단일 JSON과 연도별 샤드를 모두 읽을 수 있다. 기존 단일 JSON은 다음 수동
Action에서 자동으로 샤드 형식으로 변환된다.

## API 보완 범위

`screens` 프로필은 호출량을 줄이기 위해 다음 연도만 보완한다.

- 발행주식 수: 기업별 최초 연도, 최신 전년도, 최신 연도
- 배당 주요사항: 최신 3개 연도
- 전체 재무 API: ZIP에서 상세 재무를 찾지 못한 기업·연도

현금흐름표에 있는 배당 지급과 자사주 취득은 모든 연도에 걸쳐 ZIP에서
계산된다. 정확한 주당배당금이 10년 전체에 필요한 별도 연구에서는
`legacy-api-details`를 사용한다.
