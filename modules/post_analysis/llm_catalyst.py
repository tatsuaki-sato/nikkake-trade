"""
modules/post_analysis/llm_catalyst.py
LLMカタリスト解析(v2設計 Layer 4)。

週次ローテーションのIN候補(数銘柄)について、直近の株探ニュース見出しを
Claude (Haiku) に読ませ、「株価の持続的な材料(カタリスト)があるか」を
構造化スコアで返させる。ファクターは「数字が良い」ことしか見えないので、
その数字の背後に材料があるのか、単なる相場の勢いなのかをLLMで補完する。

現段階では通知への注記のみ(スコアリングには未反映)。効果が確認できたら
合成スコアへの組み込みを検討する。

環境変数 ANTHROPIC_API_KEY が未設定なら何もせず空dictを返す(ローテーター
本体を止めない)。コスト: Haiku、週1回、候補数件 → 月数十円程度。
"""
import os
import json
import re

MODEL = "claude-haiku-4-5"


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _build_prompt(candidates: list) -> str:
    """candidates: [{ticker, name, sector, news: [見出し, ...]}, ...]"""
    lines = [
        "あなたは日本株のアナリストです。以下の各銘柄について、直近ニュース見出しから",
        "「株価の持続的な上昇材料(カタリスト)」の有無と方向を判定してください。",
        "",
        "判定基準:",
        "- +2: 構造的な好材料(大型受注、増配・自社株買い、業績上方修正など)",
        "- +1: 弱い好材料または継続的なテーマ追い風",
        "- 0: 材料なし/判断材料不足",
        "- -1: 弱い悪材料(高値警戒報道、需給悪化の兆しなど)",
        "- -2: 明確な悪材料(下方修正、不祥事、規制リスクなど)",
        "",
        "必ず次のJSON形式のみで回答してください(前置き・説明文は不要):",
        '{"results": [{"ticker": "XXXX.T", "score": 0, "reason": "20字以内の根拠"}]}',
        "",
        "--- 銘柄とニュース ---",
    ]
    for c in candidates:
        lines.append(f"\n■ {c['name']} ({c['ticker']}) / {c.get('sector', '不明')}")
        news = c.get("news") or []
        if news:
            for n in news:
                lines.append(f"  - {n}")
        else:
            lines.append("  - (直近ニュースなし)")
    return "\n".join(lines)


def analyze_catalysts(candidates: list) -> dict:
    """IN候補のカタリストをLLMで判定する。

    candidates: [{ticker, name, sector, news: [...]}, ...]
    戻り値: {ticker: {"score": int, "reason": str}}。キー未設定・失敗時は {}。
    """
    if not llm_available():
        print("[llm_catalyst] ANTHROPIC_API_KEY 未設定のためスキップ")
        return {}
    if not candidates:
        return {}

    try:
        import anthropic
    except ImportError:
        print("[llm_catalyst] anthropic パッケージ未インストールのためスキップ")
        return {}

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": _build_prompt(candidates)}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        # 前置き付きで返ってきても最初のJSONオブジェクトを拾う
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            print(f"[llm_catalyst] JSON抽出失敗: {text[:100]}")
            return {}
        parsed = json.loads(m.group(0))
        out = {}
        for r in parsed.get("results", []):
            ticker = r.get("ticker", "")
            score = r.get("score")
            if ticker and isinstance(score, (int, float)) and -2 <= score <= 2:
                out[ticker] = {"score": int(score), "reason": str(r.get("reason", ""))[:40]}
        print(f"[llm_catalyst] カタリスト判定完了: {len(out)}銘柄")
        return out
    except anthropic.RateLimitError:
        print("[llm_catalyst] レート制限のためスキップ")
        return {}
    except anthropic.APIStatusError as e:
        print(f"[llm_catalyst] APIエラー({e.status_code})のためスキップ")
        return {}
    except Exception as e:
        print(f"[llm_catalyst] 予期しないエラーのためスキップ: {e}")
        return {}
