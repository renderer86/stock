# stock

네이버 금융 시가총액 데이터, FnGuide 과거 ROE, OpenDART 5% 이상 보유 공시를 수집해 보여주는 정적 주식 대시보드입니다.

## 준비

### Python 확인

이 프로젝트는 Python 3.13을 사용합니다. 현재 PC에서는 아래 실행 파일을 사용합니다.

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" --version
```

### 의존성 설치

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r requirements.txt
```

### OpenDART API 키 설정

전체 수집을 실행하려면 OpenDART API 키가 필요합니다.

1. [OpenDART 공식 사이트](https://opendart.fss.or.kr/)에 로그인합니다.
2. `인증키 신청/관리`에서 인증키를 발급하거나 기존 키를 확인합니다.
3. 현재 PowerShell 창에 환경변수를 설정합니다.

```powershell
$env:DART_API_KEY="발급받은키"
```

API 키는 소스 코드나 Git 저장소에 저장하지 않습니다. 새 PowerShell 창을 열면 환경변수를 다시 설정해야 합니다.

## 데이터 한 번에 수집

`run_all.py`가 다음 작업을 순서대로 실행합니다.

1. 네이버 금융 시가총액 데이터 수집
2. FnGuide 과거 ROE 수집
3. OpenDART 5% 이상 보유 공시 수집

전체 실행:

```powershell
cd C:\stock
$env:DART_API_KEY="발급받은키"
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py
```

OpenDART를 제외하고 네이버와 FnGuide만 실행:

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --skip-dart
```

중간 작업이 실패하면 이후 작업은 실행하지 않으며, 실패한 단계와 종료 코드를 출력합니다.

### 통합 실행 옵션

```powershell
# FnGuide에서 현재 ROE 15% 이상 종목만 수집
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --fnguide-min-roe 15

# 테스트를 위해 FnGuide와 OpenDART 대상을 각각 10개로 제한
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --fnguide-limit 10 --dart-limit 10

# OpenDART 우선 검토 후보만 수집
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --dart-scope priority
```

전체 옵션 확인:

```powershell
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" run_all.py --help
```

주요 옵션:

- `--skip-dart`: OpenDART 수집 생략
- `--fnguide-min-roe`: FnGuide 대상의 최소 현재 ROE, 음수이면 필터 해제
- `--fnguide-limit`: FnGuide 대상 수 제한, `0`이면 제한 없음
- `--dart-scope`: OpenDART 대상 범위 (`roe`, `priority`, `all`)
- `--dart-limit`: OpenDART 대상 수 제한, `0`이면 제한 없음
- `--naver-delay`, `--fnguide-delay`, `--dart-delay`: 각 요청 사이의 대기 시간(초)

## 생성 파일

- `data/market_sum.json`: 네이버 전체 시가총액 데이터
- `data/market_sum_by_roe.json`: ROE 기준 정렬 데이터
- `data/fnguide_roe_history.json`: FnGuide 과거 ROE 데이터
- `data/dart_major_holders.json`: OpenDART 5% 이상 보유 공시 데이터

FnGuide 파싱 실패 시 아래 디버그 파일이 추가로 생성됩니다.

- `data/fnguide_debug/<code>.html`
- `data/fnguide_debug/<code>.txt`

## 대시보드 실행

브라우저의 `fetch()`로 JSON을 읽기 때문에 `index.html`을 직접 열지 말고 로컬 서버를 실행해야 합니다.

```powershell
cd C:\stock
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" -m http.server 8000
```

브라우저에서 다음 주소로 접속합니다.

```text
http://localhost:8000
```

## 개별 수집

문제 진단이나 특정 단계만 다시 실행할 때 사용합니다.

```powershell
# 네이버 금융
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_naver_market_sum.py

# FnGuide
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_fnguide_roe_history.py

# OpenDART
& "C:\Users\rende\AppData\Local\Programs\Python\Python313\python.exe" crawler_dart_major_holders.py
```

FnGuide는 기본적으로 `data/market_sum.json`에서 현재 ROE가 10% 이상인 종목을 수집합니다. 공개 재무비율 페이지에 보이는 기간에 따라 최근 연간 결산과 최신 중간기 데이터가 함께 포함될 수 있습니다.

OpenDART 크롤러의 기본 범위는 현재 ROE가 10% 이상인 종목입니다. `data/dart_major_holders.json`이 없어도 대시보드는 해당 공시 항목을 비운 상태로 동작합니다.

## 현재 대시보드 동작

- `data/market_sum_by_roe.json`을 읽고 기본적으로 ROE 10% 이상 종목을 표시합니다.
- 거래정지 추정 종목은 흐리게 표시하고 `거래정지` 배지를 붙입니다.
- 테이블 헤더를 클릭해 정렬할 수 있습니다.
- OpenDART 기준 5% 공시, 주요 보유자, 보유비율, 최근 보고일을 표시합니다.
- 보수적, 기준, 낙관적 시나리오 기반 적정가 범위와 켈리 범위를 보여줍니다.

## GitHub Pages 배포

GitHub Pages에서는 Python 크롤러가 실행되지 않습니다. 로컬에서 `run_all.py`를 실행해 `data/*.json`을 갱신한 뒤 커밋하고 푸시해야 합니다. `.nojekyll`이 포함되어 있어 정적 파일 그대로 배포됩니다.
