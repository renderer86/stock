# stock

네이버 금융 시가총액 페이지를 수집해서 `ROE` 기준으로 보는 정적 대시보드입니다.

## 로컬 실행

### 1. Python 설치 확인

```powershell
py -3.13 --version
```

### 2. 크롤러 의존성 설치

```powershell
cd C:\stock
py -3.13 -m pip install -r requirements.txt
```

### 3. 데이터 수집

```powershell
cd C:\stock
py -3.13 crawler_naver_market_sum.py
```

실행 후 아래 파일이 생성됩니다.

- `data/market_sum.json`
- `data/market_sum_by_roe.json`

### 4. 로컬 서버 실행

`fetch()`로 JSON을 읽기 때문에 `index.html`을 더블클릭하지 말고 서버로 열어야 합니다.

```powershell
cd C:\stock
py -3.13 -m http.server 8000
```

브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:8000
```

## 현재 대시보드 동작

- `data/market_sum_by_roe.json`을 읽습니다.
- `ROE > 10` 인 종목만 표시합니다.
- 최상단 ROE 종목을 하이라이트 카드로 보여줍니다.

## GitHub Pages 배포 시 주의

- 정적 파일 배포는 가능합니다.
- 다만 GitHub Pages에서는 Python 크롤러가 실행되지 않습니다.
- 즉, 로컬에서 크롤링해서 `data/*.json`을 커밋한 뒤, 그 정적 JSON을 페이지가 읽는 방식으로 배포해야 합니다.
