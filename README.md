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

## 권장 실행 순서

```powershell
cd C:\stock
py -3.13 crawler_naver_market_sum.py
py -3.13 crawler_fnguide_roe_history.py
py -3.13 -m http.server 8000
```

## 현재 대시보드 동작

- `data/market_sum_by_roe.json`을 읽습니다.
- 기본적으로 `ROE 10% 이상` 종목을 표시합니다.
- 거래정지 추정 종목은 행 전체를 희미하게 표시하고 `거래정지` 배지를 붙입니다.
- 테이블 헤더 클릭으로 정렬할 수 있습니다.
- 단일 적정가가 아니라 `보수적 / 기준 / 낙관적` 시나리오 기반 적정가 범위와 켈리 범위를 보여줍니다.

## GitHub Pages 배포

- 이 프로젝트는 정적 파일 배포에 맞습니다.
- GitHub Pages에서는 Python 크롤러가 실행되지 않습니다.
- 즉 로컬에서 크롤링해서 `data/*.json`을 갱신한 뒤 커밋/푸시해야 합니다.
- `.nojekyll` 파일이 포함되어 있어 정적 파일 그대로 배포됩니다.

