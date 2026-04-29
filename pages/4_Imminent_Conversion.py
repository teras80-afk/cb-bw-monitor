"""
페이지 4 — 전환청구 D-30 임박 종목 (시장 전체)

설계상 주의:
- DART API에는 "특정 날짜에 전환청구개시일이 도래하는 종목"을 직접 검색하는
  엔드포인트가 없음.
- 대안: 최근 N년간 발행된 CB/BW 공시를 가져온 뒤, 각 공시의 전환청구개시일을
  계산해서 D-30 이내 도래 건을 추림.
- 시간이 꽤 걸릴 수 있으니 캐시(30분)와 진행 표시를 충분히.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from lib import (
    require_dart_or_stop, get_dart_client, parse_date_flex,
    fetch_market_cb_bw_recent,
)

st.set_page_config(page_title="전환청구 임박", page_icon="⏰", layout="wide")
st.title("⏰ 전환청구 D-30 임박 종목 (시장 전체)")
st.caption("앞으로 D-30 이내 전환청구가 가능해지는 CB/BW를 시장 전체에서 검색")

require_dart_or_stop()

st.markdown("---")

st.info(
    "💡 **작동 원리**: "
    "최근 N년 발행된 CB/BW 공시 → 각 공시의 전환청구개시일 추출 → "
    "오늘 기준 D-30 이내 도래 건만 표시. "
    "스캔 범위가 넓을수록 시간이 오래 걸립니다(수십 초~몇 분)."
)

col_y, col_d = st.columns(2)
with col_y:
    years_back = st.selectbox("과거 발행 공시 스캔 범위",
                               [1, 2, 3], index=1,
                               help="발행 후 보통 1년 뒤 전환청구 가능. "
                                    "2년이 가장 적절합니다.")
with col_d:
    days_threshold = st.selectbox("임박 기준",
                                   [7, 14, 30, 60, 90], index=2,
                                   format_func=lambda d: f"D-{d} 이내")

if not st.button("🔍 시장 전체 스캔 시작", type="primary"):
    st.stop()


@st.cache_data(ttl=1800)
def scan_market_imminent(years_back: int, days_threshold: int):
    """
    최근 N년 시장 전체 CB/BW 공시 → 각 공시의 event() 상세 조회 →
    전환청구개시일 D-N 이내 건 반환.
    """
    dart, _ = get_dart_client()
    if dart is None:
        return [], "DART 미설정"

    # 1. 최근 N년 발행 공시 모두 가져오기 (pages별로 캐시)
    days = years_back * 365
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        df_market = dart.list(start=start, end=end, kind="B", final=True)
    except Exception as e:
        return [], f"공시 리스트 조회 실패: {e}"

    if df_market is None or len(df_market) == 0:
        return [], "공시 없음"

    if "report_nm" not in df_market.columns:
        return [], "공시 응답 형식 오류"

    mask = df_market["report_nm"].str.contains(
        "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
        na=False, regex=True
    )
    df_target = df_market[mask].copy().reset_index(drop=True)
    if len(df_target) == 0:
        return [], "조건 매칭 공시 없음"

    # 2. 종목별로 그룹화 후 event() 한 번씩만 호출 (DART 호출 절약)
    today = pd.Timestamp.now().normalize()
    results = []
    seen_tickers = set()

    total = df_target["stock_code"].nunique() if "stock_code" in df_target.columns else len(df_target)
    progress = st.progress(0, text=f"종목별 상세 조회 시작... (총 {total}개사)")
    processed = 0

    for stock_code, group in df_target.groupby("stock_code"):
        processed += 1
        progress.progress(min(processed / max(total, 1), 1.0),
                          text=f"조회 중... {processed}/{total}")
        if not stock_code or pd.isna(stock_code):
            continue
        ticker = str(stock_code).zfill(6)
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        corp_name = group.iloc[0].get("corp_name", "—")

        # event 조회 (CB + BW 둘 다)
        for event_kind, type_label in [
            ("전환사채권 발행결정", "CB"),
            ("신주인수권부사채권 발행결정", "BW"),
        ]:
            try:
                ev_df = dart.event(ticker, event_kind, start=start, end=end)
            except Exception:
                continue
            if ev_df is None or len(ev_df) == 0:
                continue

            # 전환청구개시일 컬럼 찾기
            bgd_col = None
            for cand in ["cv_prd_bgd", "ex_prd_bgd", "cvRgBgd", "exRgBgd"]:
                if cand in ev_df.columns:
                    bgd_col = cand
                    break
            if bgd_col is None:
                for c in ev_df.columns:
                    if "전환" in str(c) and "시작" in str(c):
                        bgd_col = c
                        break
            if bgd_col is None:
                continue

            # 권면총액 컬럼
            fta_col = None
            for cand in ["bd_fta", "bdFta"]:
                if cand in ev_df.columns:
                    fta_col = cand
                    break

            for _, row in ev_df.iterrows():
                bgd_dt = parse_date_flex(row.get(bgd_col))
                if bgd_dt is None:
                    continue
                days_to = (bgd_dt.normalize() - today).days
                if 0 <= days_to <= days_threshold:
                    results.append({
                        "종목명": corp_name,
                        "코드": ticker,
                        "사채종류": type_label,
                        "전환청구개시일": bgd_dt.strftime("%Y-%m-%d"),
                        "D_days": days_to,
                        "권면총액": row.get(fta_col, "—") if fta_col else "—",
                    })

    progress.empty()
    return results, "ok"


with st.spinner("스캔 중... (시간이 좀 걸립니다)"):
    results, status = scan_market_imminent(years_back, days_threshold)

if status != "ok":
    st.error(f"스캔 실패: {status}")
    st.stop()

if not results:
    st.success(f"✅ 향후 D-{days_threshold} 이내 전환청구 개시 예정 종목 없음")
    st.stop()

# D-Day 오름차순 정렬
df_result = pd.DataFrame(results).sort_values("D_days").reset_index(drop=True)
df_result["D-Day"] = df_result["D_days"].apply(
    lambda d: f"D-{d}" if d > 0 else "D-Day"
)
df_result_show = df_result[["종목명", "코드", "사채종류",
                             "전환청구개시일", "D-Day", "권면총액"]]

st.warning(f"⚠️ **D-{days_threshold} 이내 전환청구 개시 예정: {len(df_result)}건** "
           f"(과거 {years_back}년 발행분 기준)")
st.dataframe(df_result_show, use_container_width=True, hide_index=True)

# CSV 다운로드
csv = df_result_show.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "📥 CSV 다운로드", data=csv,
    file_name=f"cb_bw_imminent_{datetime.now():%Y%m%d}.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption(
    "📌 발행공시상 명시된 전환청구개시일 기준입니다. "
    "이미 조기상환·전액 전환된 CB/BW도 포함될 수 있어, "
    "실제 오버행 여부는 DART 정기보고서의 미상환 잔액으로 교차 확인 필요. "
    "캐시는 30분이며, 새로고침이 필요하면 페이지를 다시 로드하세요."
)
