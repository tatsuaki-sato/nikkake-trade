"""
modules/post_analysis/full_backtest.py
本番スコア式そのもの(5ファクター+レジーム適応+急騰株ガード+セクターキャップ+
ヒステリシス)でのウォークフォワード検証。Lightプラン(遅延なし・過去5年・60回/分)前提。

factor_backtest.py(momentum+ret_3mのみ・n=11の簡易版)を置き換える本検証。
週次リバランスで検証地点150+を取り、固定12銘柄・TOPIXと比較する。

使い方(ステージは自動で順に進む。中断しても再実行すれば続きから):
    python modules/post_analysis/full_backtest.py            # fetch → fins → run を順に実行
    python modules/post_analysis/full_backtest.py --run-only # 取得済みキャッシュだけで分析

キャッシュ: data/backtest_cache/ (バー: bars/{code}.json、財務: fins/{code}.json)。
再生成可能なのでgit管理外。
"""
import sys
import os
import json
import argparse
import statistics
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.market_data import get_equities_master, get_daily_bars, get_latest_trading_date, _get_paginated
from common.factor_engine import REGIME_WEIGHTS, apply_sector_cap
from common.watchlist import DEFAULT_WATCHLIST

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "backtest_cache",
)
BENCHMARK_CODE = "13210"
LOOKBACK_YEARS = 5

# 本番 universe_rotator / factor_engine と同じパラメータ
ROTATION_SLOTS = 15
MAX_PER_SECTOR = 3
BUFFER_IN_RANK = 20
BUFFER_OUT_RANK = 40
MIN_TURNOVER_OKU = 5.0
MAX_VOL_20D = 0.05
MIN_RET_3M = -0.10
FUNDAMENTALS_TOP_N = 60

REBALANCE_STEP = 5   # 営業日(週次)
FORWARD_WINDOW = 5   # 次のリバランスまでのリターンで評価
MOM_EXCLUDE = 21
RET3M_OFF = 63
MOM_LOOKBACK = 252
RECENT_WIN = 20

FIXED_12 = [item["ticker"].replace(".T", "") + "0" for item in DEFAULT_WATCHLIST]


# ─── Stage 1: 価格データ取得(銘柄ごと・再開可能) ───────────────────────────

def fetch_bars(codes: list):
    bars_dir = os.path.join(CACHE_DIR, "bars")
    os.makedirs(bars_dir, exist_ok=True)
    latest = get_latest_trading_date()
    date_to = latest.replace("-", "")
    # 契約範囲は「今日から5年前」を起点に毎日動くため、境界ぴったりの指定は
    # 1日のズレで400になる(実測: 範囲2021-08-23〜に対し2021-08-22指定で全滅)。
    # 5営業日分のマージンを取る。
    date_from = (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=365 * LOOKBACK_YEARS - 7)).strftime("%Y%m%d")

    todo = [c for c in codes if not os.path.exists(os.path.join(bars_dir, f"{c}.json"))]
    print(f"[fetch_bars] 対象{len(codes)}銘柄中、未取得{len(todo)}銘柄 ({date_from}〜{date_to})")
    for i, code in enumerate(todo):
        try:
            rows = get_daily_bars(code, date_from=date_from, date_to=date_to)
            slim = [
                {"d": r["Date"], "c": r.get("AdjC") or r.get("C"), "va": r.get("Va")}
                for r in rows if (r.get("AdjC") or r.get("C"))
            ]
            with open(os.path.join(bars_dir, f"{code}.json"), "w") as f:
                json.dump(slim, f)
        except Exception as e:
            print(f"[fetch_bars] {code} 取得失敗(スキップ): {e}")
        if (i + 1) % 100 == 0:
            print(f"[fetch_bars] {i + 1}/{len(todo)} 完了 ({datetime.now().strftime('%H:%M:%S')})")
    print("[fetch_bars] 完了")


# ─── Stage 2: 財務履歴取得(候補になり得る銘柄のみ・再開可能) ────────────────

def load_series(code: str):
    path = os.path.join(CACHE_DIR, "bars", f"{code}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def shortlist_union(codes: list, trading_dates: list, rebalance_idx: list) -> list:
    """全リバランス地点でのモメンタム上位候補の和集合(財務を取るべき銘柄)"""
    series = {}
    for c in codes:
        s = load_series(c)
        if s:
            series[c] = {row["d"]: row for row in s}
    union = set()
    for t in rebalance_idx:
        d_t, d_ex, d_lb = trading_dates[t], trading_dates[t - MOM_EXCLUDE], trading_dates[t - MOM_LOOKBACK]
        moms = []
        for c, sm in series.items():
            if d_ex in sm and d_lb in sm and sm[d_lb]["c"]:
                moms.append((c, sm[d_ex]["c"] / sm[d_lb]["c"] - 1))
        moms.sort(key=lambda x: -x[1])
        union.update(c for c, _ in moms[:FUNDAMENTALS_TOP_N * 2])  # 余裕を持って2倍
    return sorted(union)


def fetch_fins(codes: list):
    fins_dir = os.path.join(CACHE_DIR, "fins")
    os.makedirs(fins_dir, exist_ok=True)
    todo = [c for c in codes if not os.path.exists(os.path.join(fins_dir, f"{c}.json"))]
    print(f"[fetch_fins] 対象{len(codes)}銘柄中、未取得{len(todo)}銘柄")
    for i, code in enumerate(todo):
        try:
            rows = _get_paginated("/fins/summary", {"code": code}, max_pages=2)
            slim = [
                {"disc": r.get("DiscDate"), "np": r.get("NP"), "eq": r.get("Eq"), "bps": r.get("BPS")}
                for r in rows if r.get("DiscDate")
            ]
            with open(os.path.join(fins_dir, f"{code}.json"), "w") as f:
                json.dump(slim, f)
        except Exception as e:
            print(f"[fetch_fins] {code} 取得失敗(スキップ): {e}")
        if (i + 1) % 100 == 0:
            print(f"[fetch_fins] {i + 1}/{len(todo)} 完了 ({datetime.now().strftime('%H:%M:%S')})")
    print("[fetch_fins] 完了")


# ─── Stage 3: 分析 ──────────────────────────────────────────────────────────

def load_vix_history() -> dict:
    """^VIX 5年分の {date: close}。レジーム判定のPIT再現用。"""
    import yfinance as yf
    df = yf.download("^VIX", period=f"{LOOKBACK_YEARS}y", progress=False, auto_adjust=True)
    if hasattr(df.columns, "get_level_values") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in df["Close"].dropna().items()}


def regime_at(vix_hist: dict, date: str) -> str:
    """date以前の直近VIXでレジーム判定(本番 global_macro と同じ閾値)"""
    candidates = [d for d in vix_hist if d <= date]
    if not candidates:
        return "NEUTRAL"
    vix = vix_hist[max(candidates)]
    if vix < 18.0:
        return "RISK_ON"
    if vix > 25.0:
        return "RISK_OFF"
    return "NEUTRAL"


def pit_fundamentals(fins: list, date: str) -> dict:
    """date時点で開示済みの最新財務からROE/BPSを返す(look-ahead防止)"""
    known = [r for r in fins if r["disc"] and r["disc"] <= date]
    if not known:
        return {}
    latest = max(known, key=lambda r: r["disc"])
    try:
        np_ = float(latest["np"]) if latest["np"] else None
        eq = float(latest["eq"]) if latest["eq"] else None
        bps = float(latest["bps"]) if latest["bps"] else None
        roe = (np_ / eq) if np_ is not None and eq and eq > 0 else None
        return {"roe": roe, "bps": bps}
    except (ValueError, TypeError):
        return {}


def zscore(vals: dict) -> dict:
    valid = [v for v in vals.values() if v is not None]
    if len(valid) < 3:
        return {k: 0.0 for k in vals}
    m, sd = statistics.mean(valid), statistics.pstdev(valid) or 1.0
    return {k: ((v - m) / sd if v is not None else 0.0) for k, v in vals.items()}


def run_analysis():
    master = get_equities_master()
    prime = {m["Code"]: m for m in master if m.get("MktNm") == "プライム"}

    bench = load_series(BENCHMARK_CODE)
    if not bench:
        raise RuntimeError("ベンチマーク(13210)のバー未取得。fetchを先に実行してください")
    trading_dates = [r["d"] for r in bench]
    bench_close = {r["d"]: r["c"] for r in bench}
    print(f"[run] 取引日数: {len(trading_dates)} ({trading_dates[0]}〜{trading_dates[-1]})")

    first_idx = MOM_LOOKBACK + 1
    last_idx = len(trading_dates) - FORWARD_WINDOW - 1
    rebalance_idx = list(range(first_idx, last_idx, REBALANCE_STEP))
    print(f"[run] リバランス地点: {len(rebalance_idx)}箇所(週次)")

    series = {}
    for c in prime.keys():
        s = load_series(c)
        if s:
            series[c] = {row["d"]: row for row in s}
    print(f"[run] 価格データあり: {len(series)}銘柄")

    fins_all = {}
    fins_dir = os.path.join(CACHE_DIR, "fins")
    if os.path.isdir(fins_dir):
        for fn in os.listdir(fins_dir):
            with open(os.path.join(fins_dir, fn)) as f:
                fins_all[fn[:-5]] = json.load(f)
    print(f"[run] 財務データあり: {len(fins_all)}銘柄")

    vix_hist = load_vix_history()
    print(f"[run] VIX履歴: {len(vix_hist)}日分")

    # ローテーション状態(本番と同じ状態機械)
    rotation = set()
    strikes = {}

    results = []
    for t in rebalance_idx:
        d_t = trading_dates[t]
        d_fwd = trading_dates[t + FORWARD_WINDOW]
        d_ex, d_3m, d_lb = trading_dates[t - MOM_EXCLUDE], trading_dates[t - RET3M_OFF], trading_dates[t - MOM_LOOKBACK]
        recent = trading_dates[t - RECENT_WIN + 1: t + 1]
        regime = regime_at(vix_hist, d_t)

        # 価格ファクター
        factors = {}
        for c, sm in series.items():
            if d_t not in sm or d_ex not in sm or d_lb not in sm or d_3m not in sm:
                continue
            closes = [sm[d]["c"] for d in recent if d in sm]
            vas = [sm[d]["va"] for d in recent if d in sm and sm[d]["va"]]
            if len(closes) < RECENT_WIN * 0.8 or not vas:
                continue
            rets = [closes[i + 1] / closes[i] - 1 for i in range(len(closes) - 1) if closes[i]]
            vol = statistics.pstdev(rets) if len(rets) >= 5 else None
            turn_oku = sum(vas) / len(vas) / 1e8
            mom = sm[d_ex]["c"] / sm[d_lb]["c"] - 1 if sm[d_lb]["c"] else None
            r3m = sm[d_t]["c"] / sm[d_3m]["c"] - 1 if sm[d_3m]["c"] else None
            if mom is None:
                continue
            factors[c] = {"mom": mom, "r3m": r3m, "vol": vol, "turn": turn_oku, "close": sm[d_t]["c"]}

        # フィルタ(本番と同じ)
        liquid = {
            c: f for c, f in factors.items()
            if f["turn"] >= MIN_TURNOVER_OKU
            and (f["vol"] is None or f["vol"] <= MAX_VOL_20D)
            and (f["r3m"] is None or f["r3m"] >= MIN_RET_3M)
        }
        cand = sorted(liquid.items(), key=lambda kv: -kv[1]["mom"])[:FUNDAMENTALS_TOP_N]
        cand_codes = [c for c, _ in cand]

        # PIT財務 + zスコア + レジーム別合成(本番と同じ式)
        pit = {c: pit_fundamentals(fins_all.get(c, []), d_t) for c in cand_codes}
        pbr = {c: (liquid[c]["close"] / pit[c]["bps"]) if pit[c].get("bps") and pit[c]["bps"] > 0 else None for c in cand_codes}
        mz = zscore({c: liquid[c]["mom"] for c in cand_codes})
        rz = zscore({c: liquid[c]["r3m"] for c in cand_codes})
        oz = zscore({c: pit[c].get("roe") for c in cand_codes})
        vz = zscore({c: (-pbr[c] if pbr[c] else None) for c in cand_codes})
        lz = zscore({c: (-liquid[c]["vol"] if liquid[c]["vol"] else None) for c in cand_codes})
        w = REGIME_WEIGHTS[regime]
        ranked = sorted(
            [
                {"code": c, "ticker": c, "sector": prime.get(c, {}).get("S17Nm", "不明"),
                 "score": w["momentum"] * mz[c] + w["ret_3m"] * rz[c] + w["roe"] * oz[c] + w["value"] * vz[c] + w["lowvol"] * lz[c]}
                for c in cand_codes
            ],
            key=lambda r: -r["score"],
        )

        # ローテーション状態機械(バッファ+2週ヒステリシス+セクターキャップ+RISK_OFF停止)
        rank_of = {r["code"]: i + 1 for i, r in enumerate(ranked)}
        keep, new_strikes = [], {}
        for c in rotation:
            rk = rank_of.get(c)
            if rk is None or rk > BUFFER_OUT_RANK:
                st = strikes.get(c, 0) + 1
                if st < 2:
                    new_strikes[c] = st
                    keep.append(c)
            else:
                keep.append(c)
        picked = apply_sector_cap(ranked, MAX_PER_SECTOR, top_n=BUFFER_IN_RANK)
        new_in = [] if regime == "RISK_OFF" else [r["code"] for r in picked if r["code"] not in rotation][:max(ROTATION_SLOTS - len(keep), 0)]
        rotation = set(keep) | set(new_in)
        strikes = new_strikes

        def basket_ret(codes):
            rets = []
            for c in codes:
                sm = series.get(c)
                if sm and d_t in sm and d_fwd in sm and sm[d_t]["c"]:
                    rets.append(sm[d_fwd]["c"] / sm[d_t]["c"] - 1)
            return sum(rets) / len(rets) if rets else 0.0

        r_rot = basket_ret(rotation)
        r_fix = basket_ret(FIXED_12)
        r_tpx = bench_close[d_fwd] / bench_close[d_t] - 1 if d_t in bench_close and d_fwd in bench_close else 0.0
        results.append({"date": d_t, "regime": regime, "rot": r_rot, "fix": r_fix, "tpx": r_tpx,
                        "n_universe": len(liquid), "n_rotation": len(rotation), "in": len(new_in)})

    # ─── 集計 ───
    def cum(key):
        v = 1.0
        for r in results:
            v *= 1 + r[key]
        return v - 1

    def maxdd(key):
        peak, dd, v = 1.0, 0.0, 1.0
        for r in results:
            v *= 1 + r[key]
            peak = max(peak, v)
            dd = min(dd, v / peak - 1)
        return dd

    n = len(results)
    wins_fix = sum(1 for r in results if r["rot"] > r["fix"])
    wins_tpx = sum(1 for r in results if r["rot"] > r["tpx"])
    years = n * REBALANCE_STEP / 245

    print("\n" + "=" * 60)
    print(f"検証地点: {n} (週次) / 期間: {results[0]['date']}〜{results[-1]['date']} (約{years:.1f}年)")
    print(f"{'':>14} {'累積リターン':>10} {'年率':>8} {'最大DD':>8}")
    for key, label in [("rot", "ローテーション"), ("fix", "固定12銘柄"), ("tpx", "TOPIX")]:
        c = cum(key)
        ann = (1 + c) ** (1 / years) - 1 if years > 0 else 0
        print(f"{label:>14} {c * 100:>9.1f}% {ann * 100:>7.1f}% {maxdd(key) * 100:>7.1f}%")
    print(f"\n対固定12勝率: {wins_fix}/{n} ({wins_fix / n * 100:.0f}%) / 対TOPIX勝率: {wins_tpx}/{n} ({wins_tpx / n * 100:.0f}%)")
    regs = {}
    for r in results:
        regs.setdefault(r["regime"], []).append(r["rot"] - r["fix"])
    print("レジーム別 (ローテーション-固定12 の平均超過リターン/週):")
    for k, v in regs.items():
        print(f"  {k}: {statistics.mean(v) * 100:+.2f}% (n={len(v)})")

    out_path = os.path.join(CACHE_DIR, "full_backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n詳細: {out_path}")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-only", action="store_true", help="取得済みキャッシュだけで分析")
    args = parser.parse_args()

    master = get_equities_master()
    prime_codes = sorted(m["Code"] for m in master if m.get("MktNm") == "プライム")
    all_codes = sorted(set(prime_codes) | set(FIXED_12) | {BENCHMARK_CODE})

    if not args.run_only:
        fetch_bars(all_codes)
        bench = load_series(BENCHMARK_CODE)
        trading_dates = [r["d"] for r in bench]
        first_idx = MOM_LOOKBACK + 1
        last_idx = len(trading_dates) - FORWARD_WINDOW - 1
        rebalance_idx = list(range(first_idx, last_idx, REBALANCE_STEP))
        cand = shortlist_union(prime_codes, trading_dates, rebalance_idx)
        print(f"[main] 財務取得対象(全地点の候補和集合): {len(cand)}銘柄")
        fetch_fins(cand)
    print("FETCH_DONE")
    run_analysis()
    print("BACKTEST_DONE")


if __name__ == "__main__":
    main()
