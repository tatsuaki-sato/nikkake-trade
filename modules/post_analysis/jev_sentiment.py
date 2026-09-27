"""
modules/post_analysis/jev_sentiment.py
Xセンチメントの中身判定(TypeSafe AI の Jev)。

従来の get_x_sentiment_score() は Yahoo!リアルタイム検索のヒット投稿を
数えるだけで、強気か弱気かは見ていなかった。ここでは投稿1件ずつを Jev
(文章を生成せず、型付きの判定を確率付きで返す System One モデル)に渡し、
- 銘柄の株価・業績に関する投稿か (Noul, 0〜1)
- 銘柄を並べて買いを煽る宣伝投稿か (Noul, 0〜1)
- 強気〜弱気の5段階 (Score, 0〜4)
を判定させ、宣伝を除いたうえで関連度と確信度で重み付けした平均を 0〜100 のスコアにする
(50=中立)。

環境変数 TYPESAFE_API_KEY が未設定、または判定できた投稿が無い場合は
None を返し、呼び出し側は従来の件数ベースのスコアにフォールバックする
(スキャナー本体を止めない)。
コスト: 入力 $0.042/100万トークン・出力無料。1投稿 ~300トークンなので
1銘柄10投稿でも 0.02円程度。
"""
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
MIN_CONFIDENCE = 0.5   # これ未満の強弱判定は捨てる(判断が割れている投稿)
MIN_RELEVANCE = 0.5    # 銘柄と無関係な投稿(同じ数字を含むだけ等)を除外
MAX_SPAM = 0.5         # 「買わない理由がない日本株N選」のような銘柄羅列の宣伝投稿を除外
MAX_WORKERS = 5

SENTIMENT_LEVELS = [
    "強い弱気: 売り推奨、暴落・損切り・悪材料を強調",
    "やや弱気: 先行きへの不安や高値警戒",
    "中立: 事実の共有のみ、または強弱の判断がない",
    "やや強気: 期待感、押し目買いの検討",
    "強い強気: 買い推奨、上昇・好材料を強調",
]


# 1回のジョブ実行中の呼び出し統計(失敗時のLINE通知と所要時間の確認用)
_stats_lock = threading.Lock()
_stats = {"calls": 0, "failures": 0, "errors": Counter(), "latencies": []}


def _record(latency: float, error: str | None):
    with _stats_lock:
        _stats["calls"] += 1
        _stats["latencies"].append(latency)
        if error:
            _stats["failures"] += 1
            _stats["errors"][error] += 1


def get_stats() -> dict:
    with _stats_lock:
        lat = sorted(_stats["latencies"])
        return {
            "calls": _stats["calls"],
            "failures": _stats["failures"],
            "errors": dict(_stats["errors"]),
            "avg_sec": sum(lat) / len(lat) if lat else 0.0,
            "max_sec": lat[-1] if lat else 0.0,
        }


def notify_failures(job_name: str):
    """ジョブ中に Jev の呼び出しが1件でも失敗していたら LINE に1通だけ知らせる。"""
    st = get_stats()
    print(f"[jev_sentiment] 呼び出し {st['calls']}件 / 失敗 {st['failures']}件 / "
          f"平均 {st['avg_sec']:.2f}秒 / 最大 {st['max_sec']:.2f}秒")
    if st["failures"] == 0:
        return
    errors = "、".join(f"{k}×{v}" for k, v in sorted(st["errors"].items(), key=lambda x: -x[1]))
    msg = (f"⚠️ 【Jev判定エラー】{job_name}\n"
           f"失敗 {st['failures']} / {st['calls']}件 ({errors})\n"
           f"判定できた投稿だけで採点し、全件失敗した銘柄は件数ベースにしました。"
           f"401ならAPIキー(GitHub Secretsの TYPESAFE_API_KEY)、429ならレート制限を確認してください。")
    try:
        from common.notifier import notify
        notify(msg)
    except Exception as e:
        print(f"[jev_sentiment] 失敗通知の送信エラー: {e}")


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
            "spam": {
                "type": "noul",
                "instructions": "この投稿は複数の銘柄を並べて買いを煽る宣伝・勧誘(〇〇選、億り人、一度しか言わない等)か",
            },
            "sentiment": {
                "type": "score",
                "instructions": "この投稿は株価の先行きに対して強気か弱気か",
                "criteria": SENTIMENT_LEVELS,
            },
        },
    }
    headers = {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"}
    started = time.monotonic()
    try:
        res = requests.post(API_URL, json=body, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[jev_sentiment] APIエラー({res.status_code})")
            _record(time.monotonic() - started, f"HTTP {res.status_code}")
            return None
        answers = res.json().get("answers", {})
        result = {
            "relevance": float(answers["relevant"]["noul"]),
            "spam": float(answers["spam"]["noul"]),
            "score": float(answers["sentiment"]["score"]),
            "confidence": float(answers["sentiment"]["confidence"]),
        }
        _record(time.monotonic() - started, None)
        return result
    except requests.Timeout:
        print("[jev_sentiment] タイムアウト")
        _record(time.monotonic() - started, "タイムアウト")
        return None
    except Exception as e:
        print(f"[jev_sentiment] 判定エラー: {e}")
        _record(time.monotonic() - started, type(e).__name__)
        return None


def is_usable(r: dict) -> bool:
    """集計に使う投稿か: 銘柄に関係し、宣伝ではなく、強弱判定が割れていない。"""
    return (r["relevance"] >= MIN_RELEVANCE and r["spam"] < MAX_SPAM
            and r["confidence"] >= MIN_CONFIDENCE)


def score_posts(posts: list, keyword: str) -> int | None:
    """投稿群を強気度 0〜100 (50=中立) に集計する。キー未設定・API全滅なら None。"""
    if not jev_available() or not posts:
        return None

    posts = list(dict.fromkeys(posts))  # 同じ宣伝文のコピペ投稿を1件にまとめる
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(lambda p: _judge_post(p, keyword), posts))

    judged = [r for r in results if r]
    if not judged:
        return None  # API が全滅 → 呼び出し側で件数ベースにフォールバック
    used = [r for r in judged if is_usable(r)]
    if not used:
        # 判定はできたが無関係・宣伝ばかり → 材料なしとして中立。件数ベース(=満点)に落とさない
        print(f"[jev_sentiment] {keyword}: 採用できる投稿なし → 中立 50")
        return 50
    weighted = sum(r["score"] * r["relevance"] * r["confidence"] for r in used)
    total_w = sum(r["relevance"] * r["confidence"] for r in used)

    mean = weighted / total_w                     # 0(強い弱気)〜4(強い強気)
    score = int(round(mean / (len(SENTIMENT_LEVELS) - 1) * 100))
    print(f"[jev_sentiment] {keyword}: {len(used)}/{len(posts)}件を採用 → 強気度 {score}")
    return score
