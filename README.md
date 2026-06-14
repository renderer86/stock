# stock

네이버 금융 시가총액 페이지를 수집해 `ROE` 기준으로 보는 정적 대시보드입니다.  
추가로 FnGuide `재무비율` 페이지에서 과거 ROE 이력을 수집할 수 있습니다.

## 로컬 실행

### 1. Python 확인

```powershell
py -3.13 --version
```

### 2. 의존성 설치

```powershell
cd C:\stock
py -3.13 -m pip install -r requirements.txt
```

### 3. 네이버 금융 데이터 수집

```powershell
cd C:\stock
py -3.13 crawler_naver_market_sum.py
```

생성 파일:

- `data/market_sum.json`
- `data/market_sum_by_roe.json`

### 4. FnGuide 과거 ROE 수집

기본 동작은 `data/market_sum.json` 안에서 `현재 ROE 10% 이상`인 종목만 골라 FnGuide를 수집합니다.

```powershell
cd C:\stock
py -3.13 crawler_fnguide_roe_history.py
```

생성 파일:

- `data/fnguide_roe_history.json`

옵션 예시:

```powershell
py -3.13 crawler_fnguide_roe_history.py --min-roe 15
py -3.13 crawler_fnguide_roe_history.py --min-roe -1
py -3.13 crawler_fnguide_roe_history.py --codes 005930,000660 --limit 2
```

옵션 설명:

- `--min-roe 15`: 현재 ROE 15% 이상 종목만 수집
- `--min-roe -1`: ROE 필터 끄고 전체 종목 수집
- `--codes ...`: 특정 종목만 테스트

FnGuide 파싱 실패 시 아래 디버그 파일이 생성됩니다.

- `data/fnguide_debug/<code>.html`
- `data/fnguide_debug/<code>.txt`

참고:

- FnGuide 공개 `재무비율` 페이지는 현재 `최근 연간 결산 4개 + 최신 중간기 1개` 형태로 보이는 경우가 있습니다.
- 그래서 결과 JSON은 `full_years`, `latest_periods`, `five_period_average_roe`, `four_full_year_average_roe`를 함께 저장합니다.

### 5. 로컬 서버 실행

`fetch()`로 JSON을 읽기 때문에 `index.html`을 더블클릭하지 말고 서버로 열어야 합니다.

```powershell
cd C:\stock
py -3.13 -m http.server 8000
```

브라우저 주소:

```text
http://localhost:8000
```

### 6. OpenDART 5% 공시 수집

`우선 검토 후보`에 대해 `5% 이상 보유 공시`를 붙이려면 OpenDART API 키가 필요합니다.

1. OpenDART에서 API 키 발급
2. PowerShell에서 환경변수 설정

```powershell
$env:DART_API_KEY="발급받은키"
```

3. DART 크롤러 실행

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py
```

생성 파일:

- `data/dart_major_holders.json`

옵션 예시:

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py --limit 20
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py --delay 0.4
```

참고:

- 이 스크립트는 전체 종목이 아니라 현재 `우선 검토 후보`만 대상으로 조회합니다.
- 대시보드는 `data/dart_major_holders.json`이 없으면 해당 컬럼을 비워둔 채로 계속 동작합니다.

## 권장 실행 순서

```powershell
cd C:\stock
py -3.13 crawler_naver_market_sum.py
py -3.13 crawler_fnguide_roe_history.py
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py
py -3.13 -m http.server 8000
```

## 현재 대시보드 동작

- `data/market_sum_by_roe.json`을 읽습니다.
- 기본적으로 `ROE 10% 이상` 종목을 표시합니다.
- 거래정지 추정 종목은 행 전체를 희미하게 표시하고 `거래정지` 배지를 붙입니다.
- 테이블 헤더 클릭으로 정렬할 수 있습니다.
- `우선 검토 후보`에는 OpenDART 기준 `5% 공시`, `주요 보유자`, `보유비율`, `최근 보고일`을 추가로 붙일 수 있습니다.
- 단일 적정가가 아니라 `보수적 / 기준 / 낙관적` 시나리오 기반 적정가 범위와 켈리 범위를 보여줍니다.

## GitHub Pages 배포

- 이 프로젝트는 정적 파일 배포에 맞습니다.
- GitHub Pages에서는 Python 크롤러가 실행되지 않습니다.
- 즉 로컬에서 크롤링해서 `data/*.json`을 갱신한 뒤 커밋/푸시해야 합니다.
- `.nojekyll` 파일이 포함되어 있어 정적 파일 그대로 배포됩니다.
