"""
common/factor_engine.py
J-Quants の日次クロスセクション(全銘柄1日分)データを使い、ユニバース全体を
横断的にファクター採点する。個別銘柄ごとに履歴を取得するのではなく、
必要な日付(直近20営業日 + 1ヶ月/3ヶ月/12ヶ月前の3点)だけをクロスセクションで
まとめて取るため、全銘柄対象でもAPI呼び出しは約25回で済む(v2設計 Layer 1-2)。

ファクター:
  momentum_12_1  : 12ヶ月リターンから直近1ヶ月を除いたモメンタム(短期リバーサル回避の定石)
  ret_3m         : 3ヶ月リターン
  turnover_avg20 : 直近20営業日の平均売買代金(円) — 流動性フィルタに使用
  vol_20d        : 直近20営業日の日次リターン標準偏差 — 低ボラファクター(逆符号で加点)

quality(ROE)・value(PBR) は `attach_fundamentals()` で、価格ファクターで
絞り込んだ候補(数百銘柄)だけに対して個別に fins/summary を叩いて付与する。
理由: 全銘柄分の財務データを毎回取得すると数千APIコールになり非現実的。
"""
import statistics
from datetime import datetime, timedelta

from common.market_data import get_equities_master, get_daily_bars_by_date, get_latest_trading_date, _get_paginated
from common.cache_manager import get_cached_item, set_cached_item

BENCHMARK_CODE = "13210"  # NEXT FUNDS TOPIX連動型上場投信(既存 daily_scanner の 1321.T と同一銘柄)

# 直近から数えた営業日オフセット。0=最新、19=20営業日前(turnover/volの窓)、
# 21=約1ヶ月前(momentum除外点)、63=約3ヶ月前、252=約12ヶ月前(momentum起点)
RECENT_WINDOW = 20
MOM_EXCLUDE_OFFSET = 21
RET_3M_OFFSET = 63
MOM_LOOKBACK_OFFSET = 252


def get_trading_dates(lookback_calendar_days: int = 420) -> list:
    """ベンチマーク銘柄の日足から、実際に取引のあった日付(YYYY-MM-DD)を昇順で返す。

    契約プランで取得できる最新営業日を上限とする(Freeプランは12週遅延のため、
    今日の日付を指定すると「未来日」扱いで400エラーになる)。
    """
    latest_available = get_latest_trading_date()
    date_to = datetime.strptime(latest_available, "%Y-%m-%d") if latest_available else datetime.now()
    date_from = date_to - timedelta(days=lookback_calendar_days)
    rows = _get_paginated(
        "/equities/bars/daily",
        {"code": BENCHMARK_CODE, "from": date_from.strftime("%Y%m%d"), "to": date_to.strftime("%Y%m%d")},
    )
    dates = sorted({r["Date"] for r in rows})
    return dates


def _offsets_to_dates(trading_dates: list) -> dict:
    """最新日からのオフセット(営業日数)→実際の日付、を必要な分だけ返す"""
    if len(trading_dates) < MOM_LOOKBACK_OFFSET + 1:
        raise RuntimeError(
            f"取引日数が不足しています({len(trading_dates)}日)。J-Quants Freeプランの提供期間(過去2年)を確認してください。"
        )
    needed_offsets = set(range(RECENT_WINDOW)) | {MOM_EXCLUDE_OFFSET, RET_3M_OFFSET, MOM_LOOKBACK_OFFSET}
    # trading_dates は昇順。末尾が最新(オフセット0)。
    return {off: trading_dates[-1 - off] for off in needed_offsets}


def fetch_price_snapshots(trading_dates: list) -> dict:
    """必要な日付だけクロスセクションを取得。戻り値: {date: {code: {C, Va, MktCap}}}

    呼び出し間隔は common.market_data._get 内のレート制限機構が一括で担う
    (Freeプランは5回/分と非常に厳しく、日付点数分だけでも数分かかる)。
    """
    date_map = _offsets_to_dates(trading_dates)
    unique_dates = sorted(set(date_map.values()))
    snapshots = {}
    for date in unique_dates:
        rows = get_daily_bars_by_date(date.replace("-", ""))
        snapshots[date] = {
            r["Code"]: {"C": r.get("AdjC") or r.get("C"), "Va": r.get("Va"), "MktCap": r.get("MktCap")}
            for r in rows
            if r.get("AdjC") or r.get("C")
        }
    return snapshots, date_map


def compute_price_factors(prime_codes: set) -> dict:
    """東証プライムの全銘柄について価格ベースのファクターを計算して返す。

    戻り値: {code: {momentum_12_1, ret_3m, turnover_avg20_oku, vol_20d, close}}
    データ欠損(新規上場・取引停止等)の銘柄はスキップする。
    """
    trading_dates = get_trading_dates()
    snapshots, date_map = fetch_price_snapshots(trading_dates)

    recent_dates = [date_map[i] for i in range(RECENT_WINDOW)]
    date_mom_exclude = date_map[MOM_EXCLUDE_OFFSET]
    date_ret_3m = date_map[RET_3M_OFFSET]
    date_mom_lookback = date_map[MOM_LOOKBACK_OFFSET]
    latest_date = date_map[0]

    results = {}
    for code in prime_codes:
        try:
            closes_recent = [snapshots[d][code]["C"] for d in recent_dates if code in snapshots[d]]
            if len(closes_recent) < RECENT_WINDOW * 0.8:
                continue
            c_latest = snapshots[latest_date][code]["C"]
            c_mom_exclude = snapshots[date_mom_exclude][code]["C"] if code in snapshots[date_mom_exclude] else None
            c_ret_3m = snapshots[date_ret_3m][code]["C"] if code in snapshots[date_ret_3m] else None
            c_mom_lookback = snapshots[date_mom_lookback][code]["C"] if code in snapshots[date_mom_lookback] else None

            turnovers = [snapshots[d][code]["Va"] for d in recent_dates if code in snapshots[d] and snapshots[d][code]["Va"]]
            turnover_avg20_oku = (sum(turnovers) / len(turnovers) / 1e8) if turnovers else 0.0

            daily_rets = [
                closes_recent[i] / closes_recent[i + 1] - 1
                for i in range(len(closes_recent) - 1)
                if closes_recent[i + 1]
            ]
            vol_20d = statistics.pstdev(daily_rets) if len(daily_rets) >= 5 else None

            momentum_12_1 = (
                (c_mom_exclude / c_mom_lookback - 1) if c_mom_exclude and c_mom_lookback else None
            )
            ret_3m = (c_latest / c_ret_3m - 1) if c_latest and c_ret_3m else None

            results[code] = {
                "close": c_latest,
                "momentum_12_1": momentum_12_1,
                "ret_3m": ret_3m,
                "turnover_avg20_oku": turnover_avg20_oku,
                "vol_20d": vol_20d,
                "market_cap_oku": (snapshots[latest_date][code].get("MktCap") or 0),
            }
        except (KeyError, ZeroDivisionError, TypeError):
            continue

    return results, latest_date


def attach_fundamentals(codes: list) -> dict:
    """候補銘柄(価格ファクターで絞り込んだ後の数十〜百件)のみ fins/summary から
    ROE・BPS を取得して付与。全銘柄分を毎回叩くと数千APIコールになるため、
    価格ファクターで絞った後にだけ呼ぶこと。

    決算は四半期更新なので、銘柄ごとに30日キャッシュする(Freeプラン5回/分の
    制限下では、キャッシュが効かない初回だけがコストの大半を占める)。
    """
    out = {}
    for code in codes:
        cache_key = f"jquants_fundamentals_{code}"
        cached = get_cached_item(cache_key, ttl_seconds=30 * 86400)
        if cached is not None:
            out[code] = cached
            continue
        try:
            d = _get_paginated("/fins/summary", {"code": code}, max_pages=1)
            if not d:
                out[code] = {}
            else:
                latest = sorted(d, key=lambda r: r.get("DiscDate", ""))[-1]
                np_ = float(latest["NP"]) if latest.get("NP") else None
                eq = float(latest["Eq"]) if latest.get("Eq") else None
                bps = float(latest["BPS"]) if latest.get("BPS") else None
                # 自己資本がマイナス(債務超過)だと NP/Eq がマイナス÷マイナスで
                # プラスに転じ、赤字企業が「高ROEの優良企業」として最上位に
                # 来てしまう(実例: ジャパンディスプレイ Eq=-74.1億円 NP=-198.1億円
                # → 見かけ上ROE+267%)。自己資本がプラスの場合のみ採用する。
                roe = (np_ / eq) if np_ is not None and eq and eq > 0 else None
                out[code] = {"roe": roe, "bps": bps}
        except Exception:
            out[code] = {}
        set_cached_item(cache_key, out[code])
    return out


def _zscore(values: dict) -> dict:
    """{key: float|None} → {key: zscore}。None は0扱い(平均相当)で除外はしない。"""
    valid = [v for v in values.values() if v is not None]
    if len(valid) < 3:
        return {k: 0.0 for k in values}
    mean = statistics.mean(valid)
    stdev = statistics.pstdev(valid) or 1.0
    return {k: ((v - mean) / stdev if v is not None else 0.0) for k, v in values.items()}


def build_universe_scores(
    min_turnover_oku: float = 5.0,
    fundamentals_top_n: int = 60,
    max_vol_20d: float = 0.05,
    min_ret_3m: float = -0.10,
) -> list:
    """東証プライムの全銘柄を横断採点する。

    処理順(APIコール数を抑えるため段階的に絞り込む):
      1. 銘柄マスタから東証プライムの上場銘柄コードを取得(キャッシュ24h)
      2. 全銘柄の価格ファクター(モメンタム/3ヶ月リターン/流動性/ボラ)を計算(~25 API call)
      3. 流動性フィルタで数百銘柄に絞る
      4. モメンタム上位 fundamentals_top_n 件だけ ROE/PBR を取得(未キャッシュ分だけ API call)
      5. 各ファクターをzスコア化し合成、業種(S17)を付与して返す

    fundamentals_top_n のデフォルトは60。Freeプラン(5回/分)では価格ファクター側の
    ~25コールだけで約5分かかるため、実運用(Lightプラン=60回/分)に上げるまでは
    無理に大きくしない。ウォッチリストの循環枠15+バッファ(順位40位)を賄うには
    60件あれば十分な余裕がある。

    戻り値: score降順の list[dict]
    """
    from common.market_data import RATE_LIMIT_PER_MIN
    master = get_equities_master()
    prime = {m["Code"]: m for m in master if m.get("MktNm") == "プライム"}
    print(f"[factor_engine] プライム上場: {len(prime)}銘柄")
    print(f"[factor_engine] レート制限 {RATE_LIMIT_PER_MIN}回/分 → 価格ファクター取得だけで概算 "
          f"{25 / RATE_LIMIT_PER_MIN:.0f}分程度かかる見込み")

    price_factors, as_of_date = compute_price_factors(set(prime.keys()))
    print(f"[factor_engine] 価格ファクター計算完了: {len(price_factors)}銘柄 (基準日 {as_of_date})")

    liquid = {
        c: f for c, f in price_factors.items()
        if f["turnover_avg20_oku"] >= min_turnover_oku and f["momentum_12_1"] is not None
    }
    print(f"[factor_engine] 流動性フィルタ(平均売買代金{min_turnover_oku}億円以上)後: {len(liquid)}銘柄")

    # 急騰株の独占対策: 2026-08-23のドライランで、モメンタム上位20件がAI需要
    # (半導体メモリ・銅線・レアメタル)一色の+250〜+1450%騰落に占拠される事象を確認。
    # 個別には正しい数値だが、そのまま採用すると循環枠が単一テーマの「相場もの」に
    # 汚染される。2つの条件で足切りする:
    #   - vol_20d: 直近20営業日の日次ボラが異常に高い(パラボリック相場)銘柄を除外
    #   - ret_3m: 12ヶ月では騰落大でも、直近3ヶ月で大きく崩れている(=既に天井を
    #     打って崩落中)銘柄を除外。一時的なスパイクと持続的トレンドを区別する。
    before_guard = len(liquid)
    liquid = {
        c: f for c, f in liquid.items()
        if (f["vol_20d"] is None or f["vol_20d"] <= max_vol_20d)
        and (f["ret_3m"] is None or f["ret_3m"] >= min_ret_3m)
    }
    print(f"[factor_engine] 急騰株ガード(日次ボラ{max_vol_20d*100:.0f}%以下 かつ "
          f"3ヶ月リターン{min_ret_3m*100:.0f}%以上)後: {before_guard}→{len(liquid)}銘柄")

    ranked_by_momentum = sorted(liquid.items(), key=lambda kv: kv[1]["momentum_12_1"], reverse=True)
    candidates = ranked_by_momentum[:fundamentals_top_n]
    candidate_codes = [c for c, _ in candidates]

    fundamentals = attach_fundamentals(candidate_codes)
    print(f"[factor_engine] 財務データ取得完了: {len(candidate_codes)}銘柄")

    roe_z = _zscore({c: fundamentals.get(c, {}).get("roe") for c in candidate_codes})
    pbr_by_code = {}
    for c in candidate_codes:
        bps = fundamentals.get(c, {}).get("bps")
        close = liquid[c]["close"]
        pbr_by_code[c] = (close / bps) if bps and bps > 0 else None
    # バリューは低PBRほど加点したいので符号反転してからzスコア化
    inv_pbr = {c: (-v if v else None) for c, v in pbr_by_code.items()}
    value_z = _zscore(inv_pbr)

    mom_z = _zscore({c: liquid[c]["momentum_12_1"] for c in candidate_codes})
    ret3m_z = _zscore({c: liquid[c]["ret_3m"] for c in candidate_codes})
    lowvol_z = _zscore({c: (-liquid[c]["vol_20d"] if liquid[c]["vol_20d"] else None) for c in candidate_codes})

    rows = []
    for c in candidate_codes:
        composite = (
            0.35 * mom_z[c]
            + 0.15 * ret3m_z[c]
            + 0.20 * roe_z[c]
            + 0.15 * value_z[c]
            + 0.15 * lowvol_z[c]
        )
        info = prime.get(c, {})
        rows.append({
            "code": c,
            "ticker": f"{c[:4]}.T",
            "name": info.get("CoName", ""),
            "sector": info.get("S17Nm", "不明"),
            "score": round(composite, 3),
            "momentum_12_1": liquid[c]["momentum_12_1"],
            "ret_3m": liquid[c]["ret_3m"],
            "vol_20d": liquid[c]["vol_20d"],
            "turnover_avg20_oku": liquid[c]["turnover_avg20_oku"],
            "roe": fundamentals.get(c, {}).get("roe"),
            "pbr": pbr_by_code.get(c),
            "as_of_date": as_of_date,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def apply_sector_cap(ranked_rows: list, max_per_sector: int, top_n: int) -> list:
    """スコア順に採用しつつ、業種(S17)ごとの採用数を上限で制限する"""
    sector_count = {}
    picked = []
    for row in ranked_rows:
        if len(picked) >= top_n:
            break
        sector = row["sector"]
        if sector_count.get(sector, 0) >= max_per_sector:
            continue
        picked.append(row)
        sector_count[sector] = sector_count.get(sector, 0) + 1
    return picked
