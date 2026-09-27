"""
modules/post_analysis/jev_sentiment.py
Xセンチメントの中身判定(TypeSafe AI の Jev)。

従来の get_x_sentiment_score() は Yahoo!リアルタイム検索のヒット投稿を
数えるだけで、強気か弱気かは見ていなかった。ここでは投稿1件ずつを Jev
(文章を生成せず、型付きの判定を確率付きで返す System One モデル)に渡し、
- 銘柄の株価・業績に関する投稿か (Noul, 0〜1)
- 強気〜弱気の5段階 (Score, 0〜4)
を判定させ、関連度と確信度で重み付けした平均を 0〜100 のスコアにする
(50=中立)。

環境変数 TYPESAFE_API_KEY が未設定、または判定できた投稿が無い場合は
None を返し、呼び出し側は従来の件数ベースのスコアにフォールバックする
(スキャナー本体を止めない)。
コスト: 入力 $0.042/100万トークン・出力無料。1投稿 ~300トークンなので
1銘柄10投稿でも 0.02円程度。
"""
import os
from concurrent.futures import ThreadPoolExecutor

import requests

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
MIN_CONFIDENCE = 0.5   # これ未満の強弱判定は捨てる(判断が割れている投稿)
MIN_RELEVANCE = 0.5    # 銘柄と無関係な投稿(同じ数字を含むだけ等)を除外
MAX_WORKERS = 5

SENTIMENT_LEVELS = [
    "強い弱気: 売り推奨、暴落・損切り・悪材料を強調",
    "やや弱気: 先行きへの不安や高値警戒",
    "中立: 事実の共有のみ、または強弱の判断がない",
    "やや強気: 期待感、押し目買いの検討",
    "強い強気: 買い推奨、上昇・好材料を強調",
]


def jev_available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _judge_post(post: str, keyword: str) -> dict | None:
    """1投稿を Jev で判定する。失敗時は None。"""
    body = {
        "state": post,
        "model": MODEL,
        "questions": {
            "relevant": {
                "type": "noul",
                "instructions": f"この投稿は銘柄コード{keyword}の株価・業績・売買について述べているか",
            },
            "sentiment": {
                "type": "score",
                "instructions": "この投稿は株価の先行きに対して強気か弱気か",
                "criteria": SENTIMENT_LEVELS,
            },
        },
    }
    headers = {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"}
    try:
        res = requests.post(API_URL, json=body, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[jev_sentiment] APIエラー({res.status_code})")
            return None
        answers = res.json().get("answers", {})
        return {
            "relevance": float(answers["relevant"]["noul"]),
            "score": float(answers["sentiment"]["score"]),
            "confidence": float(answers["sentiment"]["confidence"]),
        }
    except Exception as e:
        print(f"[jev_sentiment] 判定エラー: {e}")
        return None


def score_posts(posts: list, keyword: str) -> int | None:
    """投稿群を強気度 0〜100 (50=中立) に集計する。判定不能なら None。"""
    if not jev_available() or not posts:
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(lambda p: _judge_post(p, keyword), posts))

    weighted, total_w = 0.0, 0.0
    for r in results:
        if not r or r["relevance"] < MIN_RELEVANCE or r["confidence"] < MIN_CONFIDENCE:
            continue
        w = r["relevance"] * r["confidence"]
        weighted += r["score"] * w
        total_w += w
    if total_w == 0:
        return None

    mean = weighted / total_w                     # 0(強い弱気)〜4(強い強気)
    score = int(round(mean / (len(SENTIMENT_LEVELS) - 1) * 100))
    used = sum(1 for r in results if r and r["relevance"] >= MIN_RELEVANCE and r["confidence"] >= MIN_CONFIDENCE)
    print(f"[jev_sentiment] {keyword}: {used}/{len(posts)}件を採用 → 強気度 {score}")
    return score
