"""
scripts/jev_check.py
Jev(TypeSafe AI)のXセンチメント判定を目視確認する。DB書き込み・通知はしない。

1. 強気/弱気/無関係がはっきりした日本語の例文で、判定が期待どおりか確認
2. 実際の Yahoo!リアルタイム検索の投稿で、1件ずつの判定と集計スコアを表示

使い方: TYPESAFE_API_KEY=... python scripts/jev_check.py [銘柄コード ...]
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.post_analysis.advanced_scraper import get_x_posts
from modules.post_analysis.jev_sentiment import jev_available, _judge_post, is_usable, score_posts

SAMPLES = [
    ("強気", "7203", "トヨタ、決算で上方修正きた！増配もあるしまだまだ上がる。押し目は全力買い"),
    ("弱気", "7203", "7203 下方修正で失望売り。ここから一段安ありそうなので損切りした"),
    ("中立", "7203", "7203 本日の終値は2,950円、出来高は前日並み"),
    ("無関係", "7203", "今日のランチは7203円のコースでした。美味しかった"),
]


def show(label: str, code: str, post: str) -> bool:
    r = _judge_post(post, code)
    if r is None:
        print(f"  [{label}] 判定失敗: {post[:50]}")
        return False
    mark = "採用" if is_usable(r) else "除外"
    print(f"  [{label}:{mark}] 関連 {r['relevance']:.2f} / 宣伝 {r['spam']:.2f} / 強気度 {r['score']:.2f} (0弱気〜4強気)"
          f" / 確信 {r['confidence']:.2f} : {post[:60]}")
    return True


def main():
    if not jev_available():
        # キー未登録の段階でPRのチェックを赤くしないよう、警告だけ出して終える
        print("::warning::TYPESAFE_API_KEY が未設定のため Jev チェックをスキップしました")
        return

    print("== 例文での判定 ==")
    ok = all([show(label, code, text) for label, code, text in SAMPLES])
    if not ok:
        sys.exit("Jev API 呼び出しに失敗しました(上のエラー参照)")

    codes = sys.argv[1:] or ["7203", "6758", "9984"]
    for code in codes:
        print(f"\n== 実投稿: {code} ==")
        posts = get_x_posts(code)
        print(f"  取得 {len(posts)}件 (件数ベースなら {min(len(posts) * 10, 100) or 50})")
        for p in dict.fromkeys(posts):
            show("投稿", code, p)
        print(f"  → 集計スコア: {score_posts(posts, code)}")


if __name__ == "__main__":
    main()
