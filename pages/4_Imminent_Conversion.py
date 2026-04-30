"""
페이지 4 — 전환청구 D-N 임박 종목 (시장 전체)

설계 변경:
- DART API의 list 호출은 한 번에 긴 기간 요청 시 빈 결과 반환 가능성 있음
- 3개월씩 분할 조회 → 합치기 방식으로 안정성 확보
- 기본 임박 기준 D-180으로 변경 (사용자 요청)
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from lib import (
    require_dart_or_stop, get_dart_client, parse_date_flex,
)

st.set_page_config(page_title="전환청구 임박", page_icon="⏰", layout="wide")
st.title("⏰ 전환청구 임박 종목 (시장 전체)")
st.caption("앞으로 D-N 이내 전환청구가 가능해지는 CB/BW를 시장 전체에서 검색")

require_dart_or_stop()

st.markdown("---")

st.info(
    "💡 **작동 원리**: "
    "최근 N년 발행된 CB/BW 공시 → 각 공시의 전환청구개시일 추출 → "
    "오늘 기준 D-N 이내 도래 건만 표시. "
    "DART API 안정성을 위해 3개월씩 분할 조회하므로 시간이 좀 걸립니다 (1~3분)."
)

col_y, col_d = st.columns(2)
with col_y:
    years_back = st.selectbox("과거 발행 공시 스캔 범위",
                               [1, 2, 3], index=1,
                               help="발행 후 보통 1년 뒤 전환청구 가능. "
                                    "2년이 가장 적절합니다.")
with col_d:
    days_threshold = st.selectbox("임박 기준",
                                   [30, 60, 90, 180, 365], index=3,
                                   format_func=lambda d: f"D-{d} 이내")

if not st.button("🔍 시장 전체 스캔 시작", type="primary"):
    st.stop()


@st.cache_data(ttl=1800)
def fetch_market_disclosures_chunked(years_back: int) -> pd.DataFrame:
    """
    시장 전체 CB/BW 발행 공시를 3개월씩 분할 조회해서 합침.
    """
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame()

    today = datetime.now().date()
    start_total = today - timedelta(days=years_back * 365)

    # 3개월(약 90일) 단위 청크 생성
    chunks = []
    cur = start_total
    while cur < today:
        chunk_end = min(cur + timedelta(days=90), today)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)

    all_frames = []
    progress = st.progress(0, text=f"공시 리스트 조회 중... (총 {len(chunks)}개 청크)")
    for i, (s, e) in enumerate(chunks):
        progress.progress((i + 1) / len(chunks),
                          text=f"공시 조회 {i+1}/{len(chunks)} ({s} ~ {e})")
        try:
            df = dart.list(start=s.strftime("%Y-%m-%d"),
                           end=e.strftime("%Y-%m-%d"),
                           kind="B", final=True)
            if df is not None and len(df) > 0:
                all_frames.append(df)
        except Exception:
            continue
    progress.empty()

    if not all_frames:
        return pd.DataFrame()

    merged = pd.concat(all_frames, ignore_index=True)
    if "report_nm" not in merged.columns:
        return pd.DataFrame()

    mask = merged["report_nm"].str.contains(
        "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
        na=False, regex=True
    )
    return merged[mask].drop_duplicates(subset=["rcept_no"]).reset_index(drop=True)


@st.cache_data(ttl=1800)
def scan_imminent(years_back: int, days_threshold: int):
    """발행 공시 → 종목별 event() → 임박 건 추출"""
    dart, _ = get_dart_client()
    if dart is None:
        return [], "DART 미설정"

    df_target = fetch_market_disclosures_chunked(years_back)
    if df_target.empty:
        return [], "발행 공시를 찾지 못했습니다 (DART API 응답 빈값)"

    if "stock_code" not in df_target.columns:
        return [], "응답에 stock_code 컬럼 없음"

    today = pd.Timestamp.now().normalize()
    results = []
    seen = set()

    # 종목별로 한 번씩만 event 호출
    unique_tickers = df_target.groupby("stock_code").first().reset_index()
    total = len(unique_tickers)
    progress = st.progress(0, text=f"종목별 상세 조회 시작... ({total}개사)")

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y-%m-%d")

    for idx, row_meta in unique_tickers.iterrows():
        progress.progress((idx + 1) / max(total, 1),
                          text=f"조회 중... {idx+1}/{total} ({row_meta.get('corp_name', '')})")
        stock_code = row_meta.get("stock_code")
        if not stock_code or pd.isna(stock_code):
            continue
        ticker = str(stock_code).zfill(6)
        if ticker in seen:
            continue
        seen.add(ticker)
        corp_name = row_meta.get("corp_name", "—")

        for event_kind, type_label in [
            ("전환사채권 발행결정", "CB"),
            ("신주인수권부사채권 발행결정", "BW"),
        ]:
            try:
                ev_df = dart.event(ticker, event_kind, start=start_date, end=end_date)
            except Exception:
                continue
            if ev_df is None or len(ev_df) == 0:
                continue

            # 전환청구개시일 컬럼 탐색
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
                    fta_val = row.get(fta_col, "—") if fta_col else "—"
                    try:
                        fta_won = float(str(fta_val).replace(",", "").strip())
                        fta_eok = f"{fta_won/1e8:,.1f}억"
                    except Exception:
                        fta_eok = str(fta_val)

                    results.append({
                        "종목명": corp_name,
                        "코드": ticker,
                        "사채종류": type_label,
                        "전환청구개시일": bgd_dt.strftime("%Y-%m-%d"),
                        "D_days": days_to,
                        "권면총액": fta_eok,
                    })
    progress.empty()
    return results, "ok"


with st.spinner("스캔 중... 1~3분 소요"):
    results, status = scan_imminent(years_back, days_threshold)

if status != "ok":
    st.error(f"스캔 실패: {status}")
    st.caption("Streamlit 우측 하단 'Manage app' → 로그에서 상세 원인 확인 가능")
    st.stop()

if not results:
    st.success(f"✅ 향후 D-{days_threshold} 이내 전환청구 개시 예정 종목 없음")
    st.stop()

# 결과 정렬 + 표시
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
    file_name=f"cb_bw_imminent_D{days_threshold}_{datetime.now():%Y%m%d}.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption(
    "📌 발행공시상 명시된 전환청구개시일 기준입니다. "
    "이미 조기상환·전액 전환된 CB/BW도 포함될 수 있어, "
    "실제 오버행 여부는 화면 1(종목별 조회)에서 미상환 잔액 교차 확인 필요. "
    "캐시는 30분이며, 새로고침이 필요하면 페이지를 다시 로드하세요."
)
