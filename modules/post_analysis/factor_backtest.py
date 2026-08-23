"""
modules/post_analysis/factor_backtest.py
週次ローテーター(universe_rotator.py)の核となる仮説 ——
「モメンタム・ファクターで東証プライムを横断採点して循環させる方が、
固定12銘柄をただ保有するより良い結果になるか」—— を、J-Quantsの
実際の過去データ(Freeプランの契約範囲 約2年、2024-06〜2026-05)で検証する。

スコープを絞った軽量版(v1)であることに注意:
  - ROE/PBR(quality/value)は含まない。個別銘柄ごとに fins/summary を叩く必要があり、
    リバランス地点×候補数ぶんAPIコールが増えるため。momentum_12_1 と ret_3m だけで
    採点する(v2設計の合成スコアのうち mom35%+ret3m15%+lowvol15%=65%の一部)。
  - vol_20d(低ボラファクター・急騰株ガード)も含まない。20営業日窓の密なデータが
    リバランス地点ごとに必要になり、Freeプラン(5回/分)ではAPI予算を大きく超える。
    急騰株ガードは ret_3m の下限チェックだけで簡易的に代替する。
  - 流動性フィルタは20日平均売買代金の代わりに、その時点1日分の売買代金(Va)を使う
    (単日なのでノイズはあるが、リバランス地点ごとに1日分しか取得しないため)。

つまりこれは「本番のスコアリング式そのもの」の検証ではなく、
「モメンタムで循環させるという発想の骨子」の検証。厳密な検証は
vol_20d・fundamentals込みでAPI予算に余裕ができてから(Lightプラン以降)行う。

リバランス間隔: 20営業日(約1ヶ月)ごと。J-Quants Freeプランの契約範囲(約2年=
約485営業日)のうち、モメンタム計算に必要な過去252営業日 と 検証用の先読み20営業日
を確保できる範囲(オフセット32〜232営業日前)で11地点を取る。
"""
import sys
import os
import statistics
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.market_data import get_equities_master, get_daily_bars_by_date
from common.factor_engine import get_trading_dates, apply_sector_cap, BENCHMARK_CODE
from common.watchlist import load_watchlist

REBALANCE_OFFSETS = list(range(32, 233, 20))  # 最新から数えた営業日オフセット(古い→新しい順で処理)
FORWARD_WINDOW = 20   # 各リバランス地点から何営業日後のリターンで評価するか
MOM_EXCLUDE_OFFSET = 21
MOM_LOOKBACK_OFFSET = 252
RET_3M_OFFSET = 63
ROTATION_SLOTS = 15
MAX_PER_SECTOR = 3
MIN_RET_3M = -0.10
MIN_VA_OKU = 3.0  # 単日の売買代金(億円) - 20日平均フィルタ(5億円)よりは緩め


def _needed_absolute_offsets() -> set:
    needed = {0}
    for k in REBALANCE_OFFSETS:
        needed.update({k, k + MOM_EXCLUDE_OFFSET, k + RET_3M_OFFSET, k + MOM_LOOKBACK_OFFSET, k - FORWARD_WINDOW})
    return needed


def fetch_snapshots(prime_codes: set, watchlist_codes: set) -> dict:
    trading_dates = get_trading_dates()
    offsets = _needed_absolute_offsets()
    if max(offsets) >= len(trading_dates):
        raise RuntimeError(
            f"必要なオフセット(最大{max(offsets)}営業日前)が取得可能な取引日数({len(trading_dates)}日)を超えています"
        )
    offset_to_date = {off: trading_dates[-1 - off] for off in offsets}
    target_codes = prime_codes | watchlist_codes | {BENCHMARK_CODE}

    snapshots = {}
    for off in sorted(offsets):
        date = offset_to_date[off]
        rows = get_daily_bars_by_date(date.replace("-", ""))
        snapshots[off] = {
            r["Code"]: {"C": r.get("AdjC") or r.get("C"), "Va": r.get("Va")}
            for r in rows
            if r["Code"] in target_codes and (r.get("AdjC") or r.get("C"))
        }
        print(f"[factor_backtest] オフセット{off}営業日前 ({date}) 取得完了: {len(snapshots[off])}銘柄")
    return snapshots, offset_to_date


def pick_rotation_basket(snapshots: dict, k: int, prime_master: dict) -> list:
    """オフセットk時点でのローテーション採用銘柄(circa universe_rotator.pyの簡易版)を返す"""
    rows = []
    for code, info in prime_master.items():
        try:
            c_k = snapshots[k].get(code, {}).get("C")
            c_exclude = snapshots[k + MOM_EXCLUDE_OFFSET].get(code, {}).get("C")
            c_ret3m = snapshots[k + RET_3M_OFFSET].get(code, {}).get("C")
            c_lookback = snapshots[k + MOM_LOOKBACK_OFFSET].get(code, {}).get("C")
            va = snapshots[k].get(code, {}).get("Va")
            if not all([c_k, c_exclude, c_ret3m, c_lookback, va]):
                continue
            if va / 1e8 < MIN_VA_OKU:
                continue
            momentum_12_1 = c_exclude / c_lookback - 1
            ret_3m = c_k / c_ret3m - 1
            if ret_3m < MIN_RET_3M:
                continue
            rows.append({
                "code": code,
                "ticker": f"{code[:4]}.T",
                "sector": info.get("S17Nm", "不明"),
                "momentum_12_1": momentum_12_1,
                "ret_3m": ret_3m,
            })
        except (KeyError, ZeroDivisionError, TypeError):
            continue
    rows.sort(key=lambda r: r["momentum_12_1"], reverse=True)
    for i, r in enumerate(rows):
        r["score"] = -i  # apply_sector_cap は score降順を仮定しているため順位をそのままスコア化
    return apply_sector_cap(rows, MAX_PER_SECTOR, ROTATION_SLOTS)


def forward_return(snapshots: dict, k: int, code: str) -> float:
    c_now = snapshots[k].get(code, {}).get("C")
    c_future = snapshots[k - FORWARD_WINDOW].get(code, {}).get("C")
    if not c_now or not c_future:
        return None
    return c_future / c_now - 1


def run_backtest():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ファクター・バックテスト起動...")
    master = get_equities_master()
    prime_master = {m["Code"]: m for m in master if m.get("MktNm") == "プライム"}
    watchlist = load_watchlist()
    watchlist_codes = {i["ticker"].replace(".T", "") + "0" for i in watchlist}
    print(f"プライム銘柄: {len(prime_master)}件 / 現行ウォッチリスト: {len(watchlist_codes)}件")

    snapshots, offset_to_date = fetch_snapshots(set(prime_master.keys()), watchlist_codes)

    results = []
    for k in REBALANCE_OFFSETS:
        basket = pick_rotation_basket(snapshots, k, prime_master)
        basket_rets = [r for r in (forward_return(snapshots, k, b["code"]) for b in basket) if r is not None]
        watch_rets = [r for r in (forward_return(snapshots, k, c) for c in watchlist_codes) if r is not None]
        bench_ret = forward_return(snapshots, k, BENCHMARK_CODE)

        rotation_avg = statistics.mean(basket_rets) if basket_rets else None
        watch_avg = statistics.mean(watch_rets) if watch_rets else None

        results.append({
            "date": offset_to_date[k],
            "n_basket": len(basket_rets),
            "rotation_ret": rotation_avg,
            "watchlist_ret": watch_avg,
            "benchmark_ret": bench_ret,
            "basket_tickers": [b["ticker"] for b in basket],
        })
        print(f"[factor_backtest] {offset_to_date[k]}: ローテーション{rotation_avg*100 if rotation_avg else None:+.1f}% "
              f"vs 固定リスト{watch_avg*100 if watch_avg else None:+.1f}% vs TOPIX{bench_ret*100 if bench_ret else None:+.1f}%"
              if rotation_avg is not None and watch_avg is not None and bench_ret is not None else
              f"[factor_backtest] {offset_to_date[k]}: データ欠損によりスキップ")

    valid = [r for r in results if r["rotation_ret"] is not None and r["watchlist_ret"] is not None]
    print(f"\n=== 集計({len(valid)}/{len(results)}地点が有効) ===")
    if valid:
        rot_avg = statistics.mean(r["rotation_ret"] for r in valid)
        watch_avg = statistics.mean(r["watchlist_ret"] for r in valid)
        bench_avg = statistics.mean(r["benchmark_ret"] for r in valid if r["benchmark_ret"] is not None)
        win_rate = sum(1 for r in valid if r["rotation_ret"] > r["watchlist_ret"]) / len(valid)
        print(f"ローテーション平均リターン(20営業日毎): {rot_avg*100:+.2f}%")
        print(f"固定12銘柄  平均リターン(20営業日毎): {watch_avg*100:+.2f}%")
        print(f"TOPIX      平均リターン(20営業日毎): {bench_avg*100:+.2f}%")
        print(f"ローテーションが固定リストに勝った回数: {win_rate*100:.0f}% ({sum(1 for r in valid if r['rotation_ret'] > r['watchlist_ret'])}/{len(valid)})")

    return results


if __name__ == "__main__":
    run_backtest()
