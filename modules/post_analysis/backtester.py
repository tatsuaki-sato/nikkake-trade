import yfinance as yf
import pandas as pd
from tabulate import tabulate
import argparse

def run_backtest(ticker_symbol: str, hold_days: int = 5, vol_multiplier: float = 3.0, vol_ma_length: int = 10):
    print(f"[{ticker_symbol}] のデータを取得中...")
    
    # yfinanceでデータを取得（過去3年分）
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period="3y")
    
    if df.empty:
        print(f"エラー: {ticker_symbol} のデータが取得できませんでした。")
        return
        
    print(f"データ取得完了: {len(df)}日分のデータ")
    
    # 1. 出来高の移動平均を計算 (10日間)
    # df['Volume'] = df['Volume'].astype(float)
    df['Vol_MA'] = df['Volume'].rolling(window=vol_ma_length).mean()
    
    # 2. 条件1: 出来高急増 (当日の出来高 >= 過去10日平均 * 倍率)
    df['Vol_Surge'] = df['Volume'] >= (df['Vol_MA'] * vol_multiplier)
    
    # 3. 条件2: 値上がり (当日終値 > 前日終値)
    df['Price_Up'] = df['Close'] > df['Close'].shift(1)
    
    # 4. シグナル判定
    df['Buy_Signal'] = df['Vol_Surge'] & df['Price_Up']
    
    # バックテスト結果の集計用
    trades = []
    
    for i in range(len(df)):
        if df['Buy_Signal'].iloc[i]:
            # シグナルが出た翌日の始値で買う
            buy_index = i + 1
            sell_index = i + 1 + hold_days
            
            # データが未来の分（まだ存在しない日）にはみ出さないかチェック
            if sell_index < len(df):
                buy_date = df.index[buy_index].strftime('%Y-%m-%d')
                sell_date = df.index[sell_index].strftime('%Y-%m-%d')
                
                buy_price = df['Open'].iloc[buy_index]
                sell_price = df['Close'].iloc[sell_index]
                
                # 損益計算（パーセント）
                profit_pct = ((sell_price - buy_price) / buy_price) * 100
                
                trades.append({
                    "シグナル発生日": df.index[i].strftime('%Y-%m-%d'),
                    "買日": buy_date,
                    "買値": round(buy_price, 2),
                    "売日": sell_date,
                    "売値": round(sell_price, 2),
                    "損益(%)": round(profit_pct, 2),
                    "勝敗": "勝" if profit_pct > 0 else "負"
                })
                
    if not trades:
        print("指定した期間中にシグナルは発生しませんでした。")
        return

    # 結果の表示
    trades_df = pd.DataFrame(trades)
    
    wins = len(trades_df[trades_df["損益(%)"] > 0])
    losses = len(trades_df[trades_df["損益(%)"] <= 0])
    win_rate = (wins / len(trades_df)) * 100
    avg_profit = trades_df["損益(%)"].mean()
    
    print("\n========== バックテスト結果 ==========")
    print(f"対象銘柄: {ticker_symbol}")
    print(f"検証期間: {df.index[0].strftime('%Y-%m-%d')} 〜 {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"保有期間: {hold_days}営業日")
    print(f"シグナル発生回数: {len(trades_df)}回")
    print(f"勝率: {win_rate:.2f}% ({wins}勝 {losses}負)")
    print(f"平均損益率: {avg_profit:.2f}%")
    print("======================================\n")
    
    print("【トレード詳細】")
    print(tabulate(trades_df, headers='keys', tablefmt='psql', showindex=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='ルールAのバックテストを実行します。')
    parser.add_argument('--ticker', type=str, default='7203.T', help='ティッカーシンボル（例: 7203.T）')
    parser.add_argument('--hold', type=int, default=5, help='保有期間（営業日）')
    args = parser.parse_args()
    
    run_backtest(ticker_symbol=args.ticker, hold_days=args.hold)
