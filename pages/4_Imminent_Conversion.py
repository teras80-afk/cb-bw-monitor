"""
페이지 4 — 전환청구 D-N 임박 종목 (시장 전체)

설계:
- 시장 동향과 동일하게 공시 리스트만 가져옴 (빠름, 1~2분)
- 발행일 + 1년 = 대략적 전환청구 개시 추정일
- 추정값이라 정확도는 떨어지지만 후보 발굴엔 충분
- 정확한 일정은 화면 1(종목별 조회)에서 종목 단위로 확인
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from lib import require_dart_or_stop, get_dart_client

st.set_page_config(page_title="전환청구 임박", page_icon="⏰", layout="wide")
st.title("⏰ 전환청구 임박 후보 종목 (시장 전체)")
st.caption("발행일 + 1년 ≈ 전환청구 개시일 추정. 정확한 일정은 화면 1에서 종목별 확인")

require_dart_or_stop()
st.markdown("---")

st.info(
    "💡 **작동 원리 (간단 모드)**: "
    "발행 후 보통 1년 시점에 전환청구 가능해지는 점을 활용해, "
    "발행일에 1년을 더한 추정 개시일로 임박 종목을 빠르게 검색합니다. "
    "**약 30초~1분** 소요. 실제 정확한 개시일은 발행 공시마다 다르므로 "
    "관심 가는 종목은 화면 1에서 다시 조회하세요."
)

col_d, col_b = st.columns(2)
with col_d:
    days_threshold = st.selectbox("임박 기준 (앞으로 D-N 이내)",
                                   [30, 60, 90, 180, 365], index=3,
                                   format_func=lambda d: f"D-{d} 이내")
with col_b:
    look_back_d = st.selectbox("발행일 추가 여유 (지났는데 행사 시작 안 한 종목)",
                                [0, 30, 60, 90], index=2,
                                format_func=lambda d: f"D+{d}일 까지 포함" if d > 0 else "임박만 표시")

if not st.button("🔍 검색 시작", type="primary"):
    st.stop()


@st.cache_data(ttl=1800)
def fetch_market_disclosures_chunked(years_back: int = 2) -> pd.DataFrame:
    """3개월씩 분할 조회"""
    dart, _ = get_dart_client()
    if dart is None:
        return pd.DataFrame()

    today = datetime.now().date()
    start_total = today - timedelta(days=years_back * 365)

    chunks = []
    cur = start_total
    while cur < today:
        chunk_end = min(cur + timedelta(days=90), today)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)

    all_frames = []
    progress = st.progress(0, text=f"공시 리스트 조회 중... (총 {len(chunks)}개 구간)")
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

    # CB/BW 발행 공시만 추리되, [기재정정] 제외 (원래 발행 공시 우선)
    mask = merged["report_nm"].str.contains(
        "전환사채권\\s*발행결정|신주인수권부사채권\\s*발행결정",
        na=False, regex=True
    )
    return (merged[mask].drop_duplicates(subset=["rcept_no"])
            .reset_index(drop=True))


with st.spinner("발행 공시 조회 중... 약 1~2분"):
    df_market = fetch_market_disclosures_chunked(years_back=2)

if df_market.empty:
    st.error("공시 조회 실패")
    st.stop()

st.success(f"✅ 최근 2년 발행 공시 **{len(df_market)}건** 조회 완료")

# 발행일 + 1년 = 추정 전환청구개시일
df = df_market.copy()
df["발행일"] = pd.to_datetime(df["rcept_dt"], format="%Y%m%d", errors="coerce")
df = df.dropna(subset=["발행일"])
df["추정 행사 개시일"] = df["발행일"] + pd.Timedelta(days=365)

today = pd.Timestamp.now().normalize()
df["D_days"] = (df["추정 행사 개시일"] - today).dt.days

# 임박 기준 + 여유 적용
# look_back_d 만큼 과거(이미 시작된 것)도 포함
df_filtered = df[(df["D_days"] >= -look_back_d) & (df["D_days"] <= days_threshold)].copy()

if df_filtered.empty:
    st.success(f"✅ D-{days_threshold} 이내 임박 종목 없음 (단, 추정값 기준)")
    st.stop()

# 사채종류
df_filtered["사채종류"] = df_filtered["report_nm"].apply(
    lambda s: "CB" if "전환사채" in str(s) else ("BW" if "신주인수권" in str(s) else "—")
)
# D-Day 라벨
def _dlabel(d):
    if d < 0:
        return f"행사중 (+{-d}일째)"
    elif d == 0:
        return "D-Day"
    else:
        return f"D-{d}"
df_filtered["D-Day"] = df_filtered["D_days"].apply(_dlabel)

# 정렬
df_filtered = df_filtered.sort_values("D_days").reset_index(drop=True)

# DART URL 추가
df_filtered["DART 원문"] = df_filtered["rcept_no"].apply(
    lambda rn: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}"
)

# 표시용 컬럼만
show_cols = ["발행일", "회사명", "종목코드", "사채종류", "추정 행사 개시일", "D-Day", "공시명"]
df_show = df_filtered.rename(columns={
    "corp_name": "회사명",
    "stock_code": "종목코드",
    "report_nm": "공시명"
})[["발행일", "회사명", "종목코드", "사채종류", "추정 행사 개시일", "D-Day", "공시명"]]
df_show["발행일"] = df_show["발행일"].dt.strftime("%Y-%m-%d")
df_show["추정 행사 개시일"] = df_show["추정 행사 개시일"].dt.strftime("%Y-%m-%d")

n_active = (df_filtered["D_days"] < 0).sum()
n_imminent = (df_filtered["D_days"] >= 0).sum()

msgs = []
if n_active > 0:
    msgs.append(f"🔴 행사중(추정) **{n_active}건**")
if n_imminent > 0:
    msgs.append(f"🟡 D-{days_threshold} 임박 **{n_imminent}건**")

if msgs:
    st.warning(" / ".join(msgs))
st.dataframe(df_show, use_container_width=True, hide_index=True)

# CSV 다운로드
csv = df_filtered[["발행일", "corp_name", "stock_code", "사채종류",
                    "추정 행사 개시일", "D_days", "report_nm",
                    "DART 원문"]].copy()
csv["발행일"] = csv["발행일"].dt.strftime("%Y-%m-%d")
csv["추정 행사 개시일"] = csv["추정 행사 개시일"].dt.strftime("%Y-%m-%d")
csv = csv.rename(columns={
    "corp_name": "회사명", "stock_code": "종목코드",
    "D_days": "D-Day(일)", "report_nm": "공시명"
})
csv_bytes = csv.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "📥 CSV 다운로드", data=csv_bytes,
    file_name=f"cb_bw_imminent_D{days_threshold}_{datetime.now():%Y%m%d}.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption(
    "⚠️ **이 표는 추정값입니다.** 실제 전환청구개시일은 발행공시마다 다릅니다 "
    "(보통 발행 후 1년이지만, 6개월/2년 등 예외 있음). "
    "관심 종목은 화면 1(종목별 조회)에서 정확한 일정을 다시 확인하세요."
)
