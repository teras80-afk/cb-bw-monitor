"""
CB/BW Monitor — 공통 라이브러리
모든 페이지에서 공유하는 DART 클라이언트, 종목명 매핑, 헬퍼 함수.
"""
import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta

try:
    import OpenDartReader as _ODR
    _HAS_DART = True
    _DART_IMPORT_ERR = ""
except Exception as _e:
    _ODR = None
    _HAS_DART = False
    _DART_IMPORT_ERR = f"{type(_e).__name__}: {_e}"

try:
    import FinanceDataReader as fdr
    _HAS_FDR = True
except Exception:
    _HAS_FDR = False


# ─────────────────────────────────────────────────────────────
# DART 클라이언트
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_dart_client():
    """DART API 클라이언트. 반환: (client, error_msg)"""
    if not _HAS_DART:
        return None, f"OpenDartReader 로딩 실패: {_DART_IMPORT_ERR}"
    try:
        api_key = st.secrets["DART_API_KEY"]
    except Exception as e:
        return None, f"secrets에서 DART_API_KEY 읽기 실패: {type(e).__name__}: {e}"
    if not api_key or not str(api_key).strip():
        return None, "DART_API_KEY가 빈 값입니다"
    try:
        return _ODR(str(api_key).strip()), ""
    except Exception as e:
        return None, f"OpenDartReader 초기화 실패: {type(e).__name__}: {e}"


def require_dart_or_stop():
    """DART 클라이언트 없으면 페이지 정지"""
    dart, err = get_dart_client()
    if dart is None:
        st.error("❌ DART API 사용 불가")
        st.code(err or "(원인 미상)")
        st.caption("Streamlit Secrets에 `DART_API_KEY` 설정이 필요합니다. "
                   "https://opendart.fss.or.kr 에서 발급.")
        st.stop()
    return dart


# ─────────────────────────────────────────────────────────────
# 종목명 매핑 (KRX)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_ticker_name_map() -> dict:
    """KRX 전체 상장종목 코드↔이름 매핑. 실패 시 빈 dict."""
    if not _HAS_FDR:
        return {}
    try:
        df = fdr.StockListing("KRX")
        code_col = "Code" if "Code" in df.columns else "Symbol"
        return dict(zip(df[code_col].astype(str).str.zfill(6), df["Name"]))
    except Exception:
        return {}


def resolve_ticker(user_input: str, name_map: dict) -> str | None:
    """종목코드 또는 종목명으로 6자리 코드 반환"""
    s = (user_input or "").strip()
    if not s:
        return None
    if s.isdigit() and len(s) == 6:
        return s if (not name_map or s in name_map) else s
    if not name_map:
        return None
    for t, n in name_map.items():
        if n == s:
            return t
    hits = [t for t, n in name_map.items() if s in n]
    return hits[0] if len(hits) == 1 else None


@st.cache_data(ttl=86400)
def get_company_name_from_dart(ticker: str) -> str:
    """
    DART API로 종목코드 → 회사명 조회. 24시간 캐시.
    실패 시 빈 문자열 반환.
    """
    dart, _ = get_dart_client()
    if dart is None:
        return ""
    try:
        info = dart.company(ticker)
        if info is None:
            return ""
        # OpenDartReader.company()는 dict 또는 Series 반환
        if hasattr(info, "get"):
            name = info.get("corp_name", "") or info.get("stock_name", "")
        else:
            name = ""
        return str(name).strip() if name else ""
    except Exception:
        return ""


def get_company_name(ticker: str, name_map: dict = None) -> str:
    """
    종목명 조회 (우선순위: name_map → DART API → 종목코드 그대로).
    """
    if name_map and ticker in name_map:
        return name_map[ticker]
    name = get_company_name_from_dart(ticker)
    if name:
        return name
    return ticker


# ─────────────────────────────────────────────────────────────
# CB/BW 발행 공시 조회
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_cb_bw_disclosures(ticker: str, years_back: int = 5) -> pd.DataFrame:
    """최근 N년간 종목의 CB/BW 발행결정 공시 목록"""
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame()

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y-%m-%d")

    try:
        df = dart.list(ticker, start=start, end=end, kind="B", final=True)
    except Exception:
        return pd.DataFrame()

    if df is None or len(df) == 0 or "report_nm" not in df.columns:
        return pd.DataFrame()

    mask = df["report_nm"].str.contains(
        "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
        na=False, regex=True
    )
    result = df[mask].copy().reset_index(drop=True)
    if len(result) == 0:
        return result

    result["사채종류"] = result["report_nm"].apply(
        lambda s: "CB" if "전환사채" in str(s)
        else ("BW" if "신주인수권" in str(s) else "기타")
    )
    result["원문URL"] = result["rcept_no"].apply(
        lambda rn: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}"
    )
    return result


# ─────────────────────────────────────────────────────────────
# 정기보고서 채무증권 발행실적
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_debt_securities_latest(ticker: str) -> tuple[pd.DataFrame, str]:
    """가장 최근 정기보고서의 채무증권 발행실적"""
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame(), "DART API 미설정"

    current_year = datetime.now().year
    attempts = []
    for year in [current_year, current_year - 1, current_year - 2]:
        for code, label in [("11014", "3분기"), ("11012", "반기"),
                             ("11013", "1분기"), ("11011", "사업")]:
            attempts.append((year, code, label))

    last_err = ""
    for year, code, label in attempts:
        try:
            df = dart.report(ticker, "채무증권발행", year, reprt_code=code)
            if df is not None and len(df) > 0:
                return df.copy(), f"{year}년 {label}보고서"
        except Exception as e:
            last_err = str(e)[:80]
            continue

    return pd.DataFrame(), f"최근 3년 정기보고서에 채무증권 발행실적 없음 ({last_err})"


def filter_cb_bw_outstanding(df_debt: pd.DataFrame) -> pd.DataFrame:
    """채무증권에서 CB/BW 미상환 잔액 > 0만"""
    if df_debt is None or len(df_debt) == 0:
        return pd.DataFrame()

    kind_col = None
    for c in df_debt.columns:
        cl = str(c).lower()
        if "isu_nm" in cl or "종류" in str(c) or "scrits_knd" in cl:
            kind_col = c
            break
    if kind_col is None:
        result = df_debt.copy()
    else:
        mask = df_debt[kind_col].astype(str).str.contains(
            "전환사채|신주인수권부사채|CB|BW|전환|신주인수권",
            na=False, regex=True
        )
        result = df_debt[mask].copy()

    remain_col = None
    for c in result.columns:
        cl = str(c).lower()
        if "remndr" in cl or "미상환" in str(c) or "잔액" in str(c):
            remain_col = c
            break

    if remain_col is not None:
        def _to_num(x):
            try:
                s = str(x).replace(",", "").replace("원", "").strip()
                if s in ("", "-", "—", "nan"):
                    return 0
                return float(s)
            except Exception:
                return 0
        result["_잔액숫자"] = result[remain_col].apply(_to_num)
        result = result[result["_잔액숫자"] > 0].copy()
        result = result.drop(columns=["_잔액숫자"])

    return result.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 전환청구기간
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_cb_conversion_periods(ticker: str) -> pd.DataFrame:
    """CB/BW 발행공시에서 전환청구기간/전환가액 추출"""
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame()

    start = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    frames = []
    try:
        df_cb = dart.event(ticker, "전환사채발행", start=start, end=end)
        if df_cb is not None and len(df_cb) > 0:
            df_cb = df_cb.copy()
            df_cb["_사채종류"] = "CB"
            frames.append(df_cb)
    except Exception:
        pass
    try:
        df_bw = dart.event(ticker, "신주인수권부사채발행", start=start, end=end)
        if df_bw is not None and len(df_bw) > 0:
            df_bw = df_bw.copy()
            df_bw["_사채종류"] = "BW"
            frames.append(df_bw)
    except Exception:
        pass

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)

    def _find_col(candidates, keywords_kr=None):
        for c in candidates:
            if c in df.columns:
                return c
        if keywords_kr:
            for c in df.columns:
                s = str(c)
                if all(k in s for k in keywords_kr):
                    return c
        return None

    bgd_col = _find_col(
        ["cvrqpd_bgd", "cv_prd_bgd", "ex_prd_bgd", "cvRgBgd", "exRgBgd"],
        keywords_kr=["전환", "시작"]
    )
    edd_col = _find_col(
        ["cvrqpd_edd", "cv_prd_edd", "ex_prd_edd", "cvRgEdd", "exRgEdd"],
        keywords_kr=["전환", "종료"]
    )
    prc_col = _find_col(["cv_prc", "ex_prc", "cvPrc", "exPrc"])
    tm_col = _find_col(["bd_tm", "bdTm"])
    fta_col = _find_col(["bd_fta", "bdFta"])
    rcept_dt_col = _find_col(["rcept_dt", "rceptDt"])

    # ★ 전환청구개시일 폴백: 컬럼이 없거나 값이 비어있으면
    # 발행일(rcept_dt) + 1년으로 추정 (DART API 응답 누락 대응)
    if bgd_col is None and rcept_dt_col is not None:
        # 폴백: 발행일 + 365일을 추정 시작일로
        def _estimate_bgd(rcept_dt_val):
            try:
                s = str(rcept_dt_val).strip()
                if len(s) == 8 and s.isdigit():
                    dt = pd.to_datetime(s, format="%Y%m%d")
                else:
                    dt = pd.to_datetime(s, errors="coerce")
                if pd.isna(dt):
                    return None
                est = dt + pd.Timedelta(days=365)
                return est.strftime("%Y-%m-%d")
            except Exception:
                return None
        df["_추정개시일"] = df[rcept_dt_col].apply(_estimate_bgd)
        bgd_col = "_추정개시일"
        is_estimated = True
    else:
        is_estimated = False

    if bgd_col is None:
        return pd.DataFrame()

    # 비어있는 셀도 추정값으로 채우기
    if rcept_dt_col is not None and not is_estimated:
        def _fill_if_empty(row):
            v = row[bgd_col]
            if v is None or str(v).strip() in ("", "-", "—", "nan", "None"):
                # 발행일+1년 폴백
                try:
                    s = str(row[rcept_dt_col]).strip()
                    if len(s) == 8 and s.isdigit():
                        dt = pd.to_datetime(s, format="%Y%m%d")
                    else:
                        dt = pd.to_datetime(s, errors="coerce")
                    if pd.isna(dt):
                        return v
                    return (dt + pd.Timedelta(days=365)).strftime("%Y-%m-%d")
                except Exception:
                    return v
            return v
        df[bgd_col] = df.apply(_fill_if_empty, axis=1)

    out = pd.DataFrame({
        "사채종류": df["_사채종류"],
        "회차": df[tm_col] if tm_col else "-",
        "권면총액": df[fta_col] if fta_col else "-",
        "전환청구개시일": df[bgd_col],
        "전환청구종료일": df[edd_col] if edd_col else "-",
        "전환가액": df[prc_col] if prc_col else "-",
        "_추정여부": is_estimated,
    })
    return out.reset_index(drop=True)


def parse_date_flex(s):
    """다양한 포맷 날짜 → Timestamp"""
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "-", "—", "nan", "None", "NaT"):
        return None

    # 한글 날짜 형식 ("2022년 05월 25일") → "2022-05-25"로 변환
    import re
    m = re.match(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if m:
        s = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    for fmt in ["%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"]:
        try:
            result = pd.to_datetime(s, format=fmt)
            if pd.isna(result):
                continue
            return result
        except Exception:
            continue
    try:
        result = pd.to_datetime(s, errors="coerce")
        if pd.isna(result):
            return None
        return result
    except Exception:
        return None


def find_imminent_conversions(ticker: str, days_threshold: int = 180) -> list:
    """
    D-N일 이내 전환청구개시일 도래 건 반환.
    기본 D-180일(6개월 전 알림).
    """
    df = fetch_cb_conversion_periods(ticker)
    if df.empty:
        return []

    today = pd.Timestamp.now().normalize()
    results = []
    for _, row in df.iterrows():
        bgd_dt = parse_date_flex(row.get("전환청구개시일"))
        if bgd_dt is None:
            continue
        days_to = (bgd_dt.normalize() - today).days
        if 0 <= days_to <= days_threshold:
            results.append({
                "사채종류": row.get("사채종류", "-"),
                "회차": str(row.get("회차", "-")),
                "권면총액": row.get("권면총액", "-"),
                "전환청구개시일": bgd_dt.strftime("%Y-%m-%d"),
                "전환가액": row.get("전환가액", "-"),
                "D_days": days_to,
            })
    return results


def get_full_conversion_schedule(ticker: str) -> pd.DataFrame:
    """
    전체 전환청구 일정표 (과거·현재·미래 모두 포함).
    화면에 시간순으로 정렬해서 표시할 용도.
    상태 컬럼 추가: '🔴 행사중' / '🟡 임박' / '🟢 대기'
    """
    df = fetch_cb_conversion_periods(ticker)
    if df.empty:
        return pd.DataFrame()

    is_estimated = bool(df["_추정여부"].iloc[0]) if "_추정여부" in df.columns and len(df) > 0 else False

    today = pd.Timestamp.now().normalize()
    rows = []
    for _, row in df.iterrows():
        bgd_dt = parse_date_flex(row.get("전환청구개시일"))
        edd_dt = parse_date_flex(row.get("전환청구종료일"))
        if bgd_dt is None:
            continue

        days_to = (bgd_dt.normalize() - today).days
        # 상태 판정
        if days_to <= 0:
            # 시작일 지남
            if edd_dt is not None and today > edd_dt.normalize():
                status = "⚪ 종료"
                d_label = "종료"
            else:
                status = "🔴 행사중"
                d_label = "행사중"
        elif days_to <= 180:
            status = "🟡 임박"
            d_label = f"D-{days_to}"
        else:
            status = "🟢 대기"
            d_label = f"D-{days_to}"

        # 개시일 라벨에 추정 표시
        bgd_label = bgd_dt.strftime("%Y-%m-%d")
        if is_estimated:
            bgd_label += " (추정)"

        rows.append({
            "상태": status,
            "사채종류": row.get("사채종류", "-"),
            "회차": str(row.get("회차", "-")),
            "권면총액": row.get("권면총액", "-"),
            "전환청구개시일": bgd_label,
            "D-Day": d_label,
            "전환청구종료일": edd_dt.strftime("%Y-%m-%d") if edd_dt is not None else "-",
            "전환가액": row.get("전환가액", "-"),
            "_sort": days_to,
            "_estimated": is_estimated,
        })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows).sort_values("_sort").drop(
        columns=["_sort", "_estimated"]).reset_index(drop=True)
    # 추정 여부를 attrs로 저장 (페이지에서 활용)
    out.attrs["is_estimated"] = is_estimated
    return out


def get_next_conversion_date(ticker: str) -> tuple[str, int, str]:
    """
    가장 가까운 미래의 전환청구개시일 1건만 반환.
    반환: (날짜문자열, D-Day일수, 상태이모지)
    이미 지난 건은 (지난것_중_가장_가까운_종료일, ...) 또는 ("—", 99999, "")
    """
    df = fetch_cb_conversion_periods(ticker)
    if df.empty:
        return "—", 99999, ""

    today = pd.Timestamp.now().normalize()
    future_dates = []
    active_now = False

    for _, row in df.iterrows():
        bgd_dt = parse_date_flex(row.get("전환청구개시일"))
        edd_dt = parse_date_flex(row.get("전환청구종료일"))
        if bgd_dt is None:
            continue

        days_to = (bgd_dt.normalize() - today).days
        if days_to >= 0:
            future_dates.append((days_to, bgd_dt))
        else:
            # 시작일 지났는데 종료일은 안 지났으면 행사중
            if edd_dt is None or today <= edd_dt.normalize():
                active_now = True

    if active_now and not future_dates:
        return "행사중", 0, "🔴"
    if not future_dates:
        return "—", 99999, ""

    future_dates.sort(key=lambda x: x[0])
    days_to, dt = future_dates[0]
    if days_to <= 180:
        emoji = "🟡"
    else:
        emoji = "🟢"
    return dt.strftime("%Y-%m-%d"), days_to, emoji


# ─────────────────────────────────────────────────────────────
# 발행 잔액 / 전환가액 / 잠재주식수 추출 (페이지 1 강화용)
# ─────────────────────────────────────────────────────────────
def _to_float(x) -> float:
    try:
        s = str(x).replace(",", "").replace("원", "").replace("주", "").strip()
        if s in ("", "-", "—", "nan", "None"):
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def extract_balance_and_price(df_debt: pd.DataFrame) -> pd.DataFrame:
    """
    채무증권 발행실적 DF에서 미상환잔액과 전환가액을 추출하고
    잠재 출회주식수까지 계산해서 반환.
    실패 시 원본 그대로.
    """
    if df_debt is None or len(df_debt) == 0:
        return df_debt

    df = df_debt.copy()

    # 미상환잔액 컬럼
    remain_col = None
    for c in df.columns:
        cl = str(c).lower()
        if "remndr" in cl or "미상환" in str(c) or "잔액" in str(c):
            remain_col = c
            break

    # 전환가액/행사가액 컬럼
    price_col = None
    for c in df.columns:
        s = str(c)
        cl = s.lower()
        if "cv_prc" in cl or "ex_prc" in cl or "전환가" in s or "행사가" in s:
            price_col = c
            break

    if remain_col is not None:
        df["_미상환잔액(원)"] = df[remain_col].apply(_to_float)
    if price_col is not None:
        df["_전환가액(원)"] = df[price_col].apply(_to_float)

    if "_미상환잔액(원)" in df.columns and "_전환가액(원)" in df.columns:
        def _calc(row):
            bal = row["_미상환잔액(원)"]
            prc = row["_전환가액(원)"]
            if bal > 0 and prc > 0:
                return int(bal / prc)
            return 0
        df["_잠재출회주식수"] = df.apply(_calc, axis=1)

    return df


# ─────────────────────────────────────────────────────────────
# 상장주식수 (희석률 계산용)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def get_listed_shares(ticker: str) -> int:
    """KRX 상장주식수. 실패 시 0."""
    if not _HAS_FDR:
        return 0
    try:
        df = fdr.StockListing("KRX")
        code_col = "Code" if "Code" in df.columns else "Symbol"
        df[code_col] = df[code_col].astype(str).str.zfill(6)
        row = df[df[code_col] == ticker]
        if len(row) == 0:
            return 0
        for c in ["Shares", "Stocks", "MarketCap", "ListedShares"]:
            if c in row.columns:
                v = _to_float(row.iloc[0][c])
                if v > 0:
                    return int(v)
        return 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────
# 시장 전체 CB/BW 신규 발행 공시 (페이지 2 / 페이지 4용)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800)
def fetch_market_cb_bw_recent(days_back: int = 30) -> pd.DataFrame:
    """
    최근 N일간 시장 전체 CB/BW 발행 공시 (특정 종목 한정 X).
    DART list API에 corp_code 미지정 + kind='B' 사용.
    """
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame()

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        df = dart.list(start=start, end=end, kind="B", final=True)
    except Exception:
        return pd.DataFrame()

    if df is None or len(df) == 0 or "report_nm" not in df.columns:
        return pd.DataFrame()

    mask = df["report_nm"].str.contains(
        "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
        na=False, regex=True
    )
    result = df[mask].copy().reset_index(drop=True)
    if len(result) == 0:
        return result

    result["사채종류"] = result["report_nm"].apply(
        lambda s: "CB" if "전환사채" in str(s)
        else ("BW" if "신주인수권" in str(s) else "기타")
    )
    result["원문URL"] = result["rcept_no"].apply(
        lambda rn: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}"
    )
    return result


# ─────────────────────────────────────────────────────────────
# GitHub 연동 (관심종목 저장용)
# ─────────────────────────────────────────────────────────────
def _github_config():
    try:
        return {
            "token": st.secrets["GITHUB_TOKEN"],
            "repo": st.secrets["GITHUB_REPO"],
            "branch": st.secrets.get("GITHUB_BRANCH", "main"),
            "path": st.secrets.get("CB_WATCHLIST_PATH", "cb_watchlist.txt"),
        }
    except Exception:
        return None


def github_get_watchlist():
    cfg = _github_config()
    if not cfg:
        return "", None
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    headers = {"Authorization": f"Bearer {cfg['token']}",
               "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(url, headers=headers,
                         params={"ref": cfg["branch"]}, timeout=10)
        if r.status_code == 200:
            js = r.json()
            return base64.b64decode(js["content"]).decode("utf-8"), js["sha"]
    except Exception:
        pass
    return "", None


def github_put_watchlist(new_content, sha):
    cfg = _github_config()
    if not cfg:
        return False, "GitHub 연동 미설정"
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    headers = {"Authorization": f"Bearer {cfg['token']}",
               "Accept": "application/vnd.github+json"}
    body = {
        "message": f"Update CB/BW watchlist ({datetime.now():%Y-%m-%d %H:%M})",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        body["sha"] = sha
    try:
        r = requests.put(url, headers=headers, json=body, timeout=10)
        if r.status_code in (200, 201):
            return True, "저장 완료"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def parse_watchlist(text):
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.startswith("#")]
