"""
modules/post_analysis/universe_rotator.py
週次ウォッチリスト・ローテーター(v2設計 Layer 2/5)。

東証プライム全銘柄をファクター(モメンタム/3ヶ月リターン/ROE/PBR/低ボラ)で
横断採点し、ウォッチリストの `rotation` 枠だけを入れ替える。`core` 枠は対象外。

循環ルール(ドライラン検証で確認した「急騰株の独占」「振れすぎる回転」への対策):
  - バッファランク: 上位 BUFFER_IN_RANK 以内で新規IN、
    下位(BUFFER_OUT_RANK位圏外)に落ちて初めてOUT候補。IN/OUT境界を離して回転を抑える。
  - ヒステリシス: OUT候補になっても即除外せず、2週連続で基準を割った銘柄だけ除外する
    (`data/rotation_state.json` に「何週連続で基準割れか」を記録)。
  - セクターキャップ: 業種(S17)ごとに循環枠内の採用数を制限。

DBの `watchlist` テーブルには一切書き込まず、生成した差分を通知するだけの
ドライランとして扱う(v2設計 Phase 2: まずウォークフォワードで妥当性を検証してから
本稼働に配線する方針)。本稼働化する際は `apply=True` で呼び出すこと。
"""
import os
import json
from datetime import datetime

from common.factor_engine import build_universe_scores, apply_sector_cap
from common.global_macro import get_market_regime
from common.watchlist import load_watchlist, save_watchlist
from common.notifier import notify

ROTATION_SLOTS = 15
MAX_PER_SECTOR = 3
BUFFER_IN_RANK = 20    # この順位以内なら新規IN対象
BUFFER_OUT_RANK = 40   # この順位より外に落ちたらOUT候補(2週連続で確定)
MIN_TURNOVER_OKU = 5.0

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "rotation_state.json",
)


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def decide_rotation(ranked_rows: list, current_rotation_tickers: set) -> dict:
    """スコア順リストと現在の循環枠から IN/OUT を決める(ヒステリシス込み)。

    戻り値: {"keep": [...], "in": [...], "out": [...], "watch_out": [...], "new_state": {...}}
    watch_out は「今回基準を割ったが、まだ1回目なので猶予中」の銘柄。
    """
    state = _load_state()
    rank_by_ticker = {r["ticker"]: i + 1 for i, r in enumerate(ranked_rows)}
    row_by_ticker = {r["ticker"]: r for r in ranked_rows}

    keep, out, watch_out = [], [], []
    new_state = {}

    for ticker in current_rotation_tickers:
        rank = rank_by_ticker.get(ticker)
        if rank is None or rank > BUFFER_OUT_RANK:
            strikes = state.get(ticker, 0) + 1
            if strikes >= 2:
                out.append({"ticker": ticker, "rank": rank, "reason": "2週連続で基準圏外(順位40位超)"})
            else:
                watch_out.append({"ticker": ticker, "rank": rank})
                new_state[ticker] = strikes
                keep.append(ticker)
        else:
            keep.append(ticker)

    # セクターキャップは「現状維持(keep)分」も加味して適用
    picked = apply_sector_cap(ranked_rows, MAX_PER_SECTOR, top_n=BUFFER_IN_RANK)
    candidates_in = [
        row_by_ticker[r["ticker"]] for r in picked
        if r["ticker"] not in current_rotation_tickers
    ]
    slots_open = ROTATION_SLOTS - len(keep)
    new_in = candidates_in[:max(slots_open, 0)]

    return {
        "keep": keep,
        "in": new_in,
        "out": out,
        "watch_out": watch_out,
        "new_state": new_state,
    }


def format_notification(decision: dict, as_of_date: str) -> str:
    regime_label = {
        "RISK_ON": "リスクオン(モメンタム重視)",
        "NEUTRAL": "中立(標準配分)",
        "RISK_OFF": "リスクオフ(防御ファクター重視・新規IN停止)",
    }.get(decision.get("regime", "NEUTRAL"), "中立")
    lines = [
        f"🔁 **【週次ウォッチリスト・ローテーション】** (基準日: {as_of_date})",
        f"🌐 レジーム: {regime_label}\n",
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
        lines.append("\n⚠️ **猶予中(来週も基準割れならOUT)**")
        for w in decision["watch_out"]:
            rank_str = w["rank"] if w["rank"] else "圏外"
            lines.append(f"・{w['ticker']} — 順位{rank_str}")
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
    current_rotation = {i["ticker"] for i in watchlist if i.get("tier") == "rotation"}

    decision = decide_rotation(ranked_rows, current_rotation)
    decision["regime"] = regime

    # リスクオフ時は新規INを停止する(下落局面での逆張り的な入れ替えは
    # 簡易バックテストでも固定リストに大きく負けた地点があった箇所)。
    # OUT(悪化銘柄の退出)と猶予カウントは通常どおり進める。
    if regime == "RISK_OFF" and decision["in"]:
        print(f"RISK_OFFのため新規IN {len(decision['in'])}件を見送り")
        decision["in_suspended"] = decision["in"]
        decision["in"] = []
    else:
        decision["in_suspended"] = []

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
        existing_tickers = {i["ticker"] for i in new_watchlist}
        today = datetime.now().strftime("%Y-%m-%d")
        for r in decision["in"]:
            if r["ticker"] not in existing_tickers:
                new_watchlist.append({
                    "ticker": r["ticker"],
                    "tier": "rotation",
                    "added_at": today,
                    "reason": f"週次ローテーション(順位{ranked_rows.index(r)+1}位, {r['sector']})",
                })
        save_watchlist(new_watchlist)
        _save_state(decision["new_state"])
        print(f"ウォッチリスト更新完了: {len(new_watchlist)}銘柄")
    else:
        print("apply=False のためドライランのみ(ウォッチリストは更新していません)")

    return decision


if __name__ == "__main__":
    # 本稼働配線前のデフォルトはドライラン。実際にDBを更新する場合は
    # run_universe_rotator(apply=True) で呼び出すこと。
    run_universe_rotator(apply=False)
