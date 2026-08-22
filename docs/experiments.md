# バックテスト実験ログ

`modules/post_analysis/backtester.py`はスキャナーには組み込まれておらず、手動実行した結果はターミナルに出力されるだけで残らない。閾値やパラメータを調整する判断のもとになった実験は、ここに残す。

実行コマンド:
```bash
python modules/post_analysis/backtester.py TICKER --hold-days 5 --vol-multiplier 3.0
```

## テンプレート

```markdown
### YYYY-MM-DD: <何を試したか>

**コマンド**: 実際に実行したコマンド(パラメータ込み)
**対象**: どの銘柄・期間
**結果**: 勝率・平均リターンなど、出力された数値
**結論**: この結果を受けて何を変えた/変えなかったか(→ 恒久的な変更なら [[docs/decisions.md]] にも記録)
```

---

まだ記録された実験はありません。`backtester.py`を実行したら、上記テンプレートに沿ってここに追記してください。
