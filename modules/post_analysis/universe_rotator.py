"""
modules/post_analysis/universe_rotator.py
週次ウォッチリスト・ローテーター(v2設計 Layer 2/5)。

東証プライム全銘柄をファクター(モメンタム/3ヶ月リターン/ROE/PBR/低ボラ)で
横断採点し、ウォッチリストを入れ替える。入れ替えの対象外は「実際に保有中の銘柄」
(リアル購入ポートフォリオに登録中の銘柄)だけ。以前の core 枠(手動固定)は
2026-09-27 に廃止した。

循環ルール:
  - バッファランク: 上位 BUFFER_IN_RANK 以内で新規IN、BUFFER_OUT_RANK 位より外で基準割れ。
  - 猶予(ストライク): 基準割れ1回目は残し、累計2回でOUT。途中で BUFFER_IN_RANK 以内まで
    戻れば0にリセットするが、IN〜OUTの間(21〜30位)に戻っただけではカウントを据え置く。
    境界付近を行ったり来たりする銘柄が「2週連続」を満たさず居座るのを防ぐため。
  - 押し出し: 枠が埋まっていても、SWAP_IN_RANK 位以内の新候補がいれば、既存銘柄のうち
    BUFFER_IN_RANK 位より下で一番順位の悪いものと入れ替える(週 MAX_SWAPS 件まで)。
  - セクターキャップ: 業種(S17)ごとに新規IN候補の採用数を制限。
  - 状態(strikes)はSupabaseのwatchlist項目自体に持たせる(CIランナーのファイルは毎回消える)。

位置づけ(2026-08-25確定、docs/decisions.md参照): ウォッチリストは「買うリスト」では
なく daily_scanner / trend_predictor の候補プール。実際のシグナルは従来どおり
70点のクオンツ判定が門番をする。apply=True(自動反映)で運用。
"""
import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.factor_engine import build_universe_scores, apply_sector_cap
from common.global_macro import get_market_regime
from common.watchlist import load_watchlist, save_watchlist, get_held_tickers
from common.notifier import notify

ROTATION_SLOTS = 20    # 循環枠(保有中の銘柄は数えない)。旧 core 5 + rotation 15 と同じ総数
MAX_PER_SECTOR = 3
BUFFER_IN_RANK = 20    # この順位以内なら新規IN対象。ここまで戻ればストライクもリセット
BUFFER_OUT_RANK = 30   # この順位より外なら基準割れ(累計2回でOUT)
SWAP_IN_RANK = 10      # 枠が埋まっていても、この順位以内の新候補は既存銘柄を押し出せる
MAX_SWAPS = 3          # 押し出しは週この件数まで(振れすぎる回転を抑える)
MIN_TURNOVER_OKU = 5.0


def decide_rotation(ranked_rows: list, watchlist_tickers: set, strikes_state: dict = None,
                    held_tickers: set = None, allow_in: bool = True) -> dict:
    """スコア順リストと現在のウォッチリストから IN/OUT を決める。

    watchlist_tickers: 現在のウォッチリスト全銘柄
    strikes_state: {ticker: 基準割れ回数}(watchlist項目の "strikes" フィールド由来)
    held_tickers: 保有中の銘柄。ウォッチリストにあっても入れ替え対象外・枠数にも数えない
    allow_in: False(リスクオフ)なら新規INと押し出しを止め、候補は in_suspended に返す。
              基準割れによるOUTと猶予カウントは通常どおり進める。
    戻り値: {"keep", "in", "out", "watch_out", "held", "in_suspended", "new_state"}
    """
    state = strikes_state or {}
    held = set(held_tickers or ()) & set(watchlist_tickers)
    rank_by_ticker = {r["ticker"]: i + 1 for i, r in enumerate(ranked_rows)}
    row_by_ticker = {r["ticker"]: r for r in ranked_rows}

    keep, out, watch_out = [], [], []
    new_state = {}

    for ticker in sorted(set(watchlist_tickers) - held):
        rank = rank_by_ticker.get(ticker)
        prev = state.get(ticker, 0)
        if rank is not None and rank <= BUFFER_IN_RANK:
            keep.append(ticker)  # 十分な順位 → リセット
        elif rank is not None and rank <= BUFFER_OUT_RANK:
            keep.append(ticker)  # 境界圏内 → カウント据え置き
            if prev:
                new_state[ticker] = prev
                watch_out.append({"ticker": ticker, "rank": rank, "strikes": prev})
        else:
            strikes = prev + 1
            if strikes >= 2:
                out.append({"ticker": ticker, "rank": rank,
                            "reason": f"基準割れ{strikes}回目(順位{BUFFER_OUT_RANK}位より下)"})
            else:
                keep.append(ticker)
                new_state[ticker] = strikes
                watch_out.append({"ticker": ticker, "rank": rank, "strikes": strikes})

    # 新規IN候補: ウォッチリストに既にある銘柄(保有中を含む)は除外。
    # 除外しないと、既存銘柄がIN枠を1つ消費したのに実際は追加されない。
    picked = apply_sector_cap(
        [r for r in ranked_rows if r["ticker"] not in watchlist_tickers],
        MAX_PER_SECTOR, top_n=BUFFER_IN_RANK,
    )
    picked = [row_by_ticker[r["ticker"]] for r in picked if rank_by_ticker[r["ticker"]] <= BUFFER_IN_RANK]

    slots_open = max(ROTATION_SLOTS - len(keep), 0)
    new_in = picked[:slots_open]
    remaining = picked[slots_open:]

    # 押し出し: 枠が埋まっていても上位の新候補は、順位の悪い既存銘柄と入れ替える
    def _rank_or_inf(t):
        r = rank_by_ticker.get(t)
        return r if r is not None else float("inf")

    displaced = []
    for cand in remaining:
        if len(displaced) >= MAX_SWAPS or rank_by_ticker[cand["ticker"]] > SWAP_IN_RANK:
            break
        weakest = max(keep, key=_rank_or_inf, default=None)
        if weakest is None or _rank_or_inf(weakest) <= BUFFER_IN_RANK:
            break
        keep.remove(weakest)
        new_state.pop(weakest, None)
        watch_out = [w for w in watch_out if w["ticker"] != weakest]
        displaced.append({
            "ticker": weakest, "rank": rank_by_ticker.get(weakest),
            "reason": f"入替(上位{rank_by_ticker[cand['ticker']]}位の新候補 "
                      f"{cand['ticker']} に枠を譲る)",
        })
        new_in.append(cand)

    in_suspended = []
    if not allow_in:
        in_suspended = new_in
        new_in = []
        # 押し出しも取り消し(入れ替え先が入らないので枠を空けない)
        for d in displaced:
            keep.append(d["ticker"])
            prev = state.get(d["ticker"], 0)
            if prev:
                new_state[d["ticker"]] = prev
        displaced = []

    return {
        "keep": keep,
        "in": new_in,
        "out": out + displaced,
        "watch_out": watch_out,
        "held": sorted(held),
        "in_suspended": in_suspended,
        "new_state": new_state,
    }


def format_notification(decision: dict, as_of_date: str) -> str:
    regime_label = {
        "RISK_ON": "リスクオン(モメンタム重視)",
        "NEUTRAL": "中立(標準配分)",
        "RISK_OFF": "リスクオフ(防御ファクター重視・新規IN停止)",
    }.get(decision.get("regime", "NEUTRAL"), "中立")
    applied_label = "✅ ウォッチリストに自動反映済み" if decision.get("applied") else "ℹ️ 提案のみ(未反映)"
    lines = [
        f"🔁 **【週次ウォッチリスト・ローテーション】** (基準日: {as_of_date})",
        f"🌐 レジーム: {regime_label} / {applied_label}",
        "※スキャン候補の入れ替えです。実際のシグナルは従来どおりクオンツ判定(70点)を通過したもののみ。\n",
    ]
    if decision.get("in_suspended"):
        lines.append(f"⏸️ リスクオフのため新規IN {len(decision['in_suspended'])}件を見送り: "
                     + ", ".join(f"{r['name']}({r['code']})" for r in decision["in_suspended"]))
    catalysts = decision.get("catalysts", {})
    catalyst_marks = {2: "🟢🟢", 1: "🟢", 0: "⚪", -1: "🔴", -2: "🔴🔴"}
    if decision["in"]:
        lines.append("📥 **IN**")
        for r in decision["in"]:
            line = (
                f"・{r['name']}({r['code']}) — {r['sector']} / "
                f"モメンタム{r['momentum_12_1']*100:+.1f}% / スコア{r['score']}"
            )
            cat = catalysts.get(r["ticker"])
            if cat:
                line += f"\n   └ 材料{catalyst_marks.get(cat['score'], '⚪')} {cat['reason']}"
            lines.append(line)
    if decision["out"]:
        lines.append("\n📤 **OUT**")
        for o in decision["out"]:
            lines.append(f"・{o['ticker']} — {o['reason']}")
    if decision["watch_out"]:
        lines.append(f"\n⚠️ **猶予中(次に{BUFFER_OUT_RANK}位より下ならOUT、{BUFFER_IN_RANK}位以内に戻ればリセット)**")
        for w in decision["watch_out"]:
            rank_str = w["rank"] if w["rank"] else "圏外"
            lines.append(f"・{w['ticker']} — 順位{rank_str} / 基準割れ{w.get('strikes', 1)}回")
    if decision.get("held"):
        lines.append("\n🔒 保有中のため入れ替え対象外: " + ", ".join(decision["held"]))
    if not decision["in"] and not decision["out"]:
        lines.append("変更なし。循環枠は全銘柄が基準内です。")
    return "\n".join(lines)


def run_universe_rotator(apply: bool = False, notify_result: bool = True):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 週次ユニバース・ローテーター起動...")

    regime = get_market_regime()
    print(f"マクロレジーム: {regime}")

    ranked_rows = build_universe_scores(min_turnover_oku=MIN_TURNOVER_OKU, regime=regime)
    as_of_date = ranked_rows[0]["as_of_date"] if ranked_rows else "不明"
    print(f"採点完了: {len(ranked_rows)}銘柄 (基準日 {as_of_date})")

    watchlist = load_watchlist()
    watchlist_tickers = {i["ticker"] for i in watchlist}
    strikes_state = {i["ticker"]: i.get("strikes", 0) for i in watchlist if i.get("strikes")}
    try:
        held_tickers = get_held_tickers()
    except Exception as e:
        # 保有銘柄が読めないまま回すと実保有株を外しかねないので、今週は提案のみにする
        print(f"⚠️ 保有銘柄の取得に失敗、今週はウォッチリストを更新しません: {e}")
        held_tickers = set()
        apply = False
    print(f"保有中(入れ替え対象外): {sorted(held_tickers & watchlist_tickers)}")

    # リスクオフ時は新規IN・押し出しを停止する(下落局面での逆張り的な入れ替えは
    # 簡易バックテストでも固定リストに大きく負けた地点があった箇所)。
    # OUT(悪化銘柄の退出)と猶予カウントは通常どおり進める。
    decision = decide_rotation(ranked_rows, watchlist_tickers, strikes_state,
                               held_tickers=held_tickers, allow_in=(regime != "RISK_OFF"))
    decision["regime"] = regime
    decision["applied"] = apply
    if decision["in_suspended"]:
        print(f"RISK_OFFのため新規IN {len(decision['in_suspended'])}件を見送り")

    print(f"IN: {len(decision['in'])} / OUT: {len(decision['out'])} / 猶予: {len(decision['watch_out'])}")

    # LLMカタリスト解析: IN候補の直近ニュースをClaudeに読ませ、材料の有無を注記。
    # ANTHROPIC_API_KEY 未設定なら黙ってスキップ(空dict)。
    decision["catalysts"] = {}
    if decision["in"]:
        try:
            from modules.post_analysis.advanced_scraper import get_kabutan_news
            from modules.post_analysis.llm_catalyst import analyze_catalysts
            candidates = [
                {"ticker": r["ticker"], "name": r["name"], "sector": r["sector"],
                 "news": get_kabutan_news(r["ticker"])}
                for r in decision["in"]
            ]
            decision["catalysts"] = analyze_catalysts(candidates)
        except Exception as e:
            print(f"カタリスト解析エラー(注記なしで継続): {e}")

    if notify_result:
        notify(format_notification(decision, as_of_date))

    if apply:
        out_tickers = {o["ticker"] for o in decision["out"]}
        new_watchlist = [i for i in watchlist if i["ticker"] not in out_tickers]
        today = datetime.now().strftime("%Y-%m-%d")
        # ヒステリシス状態(連続基準割れ週数)を項目自体に持たせて永続化する。
        # new_state に無い銘柄(上位に戻った銘柄・保有中の銘柄)はカウントを消す。
        for i in new_watchlist:
            i["tier"] = "rotation"
            strikes = decision["new_state"].get(i["ticker"])
            if strikes:
                i["strikes"] = strikes
            else:
                i.pop("strikes", None)
        existing_tickers = {i["ticker"] for i in new_watchlist}
        for r in decision["in"]:
            if r["ticker"] not in existing_tickers:
                new_watchlist.append({
                    "ticker": r["ticker"],
                    "tier": "rotation",
                    "added_at": today,
                    "reason": f"週次ローテーション(順位{ranked_rows.index(r)+1}位, {r['sector']})",
                })
        save_watchlist(new_watchlist)
        print(f"ウォッチリスト更新完了: {len(new_watchlist)}銘柄")
    else:
        print("apply=False のためドライランのみ(ウォッチリストは更新していません)")

    return decision


if __name__ == "__main__":
    run_universe_rotator(apply=True)
