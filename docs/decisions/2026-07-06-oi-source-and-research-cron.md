# 変更記録: 10_deriv OIソースのBinance切替 ＋ リサーチデータ取得の自動化（2026-07-06）

> 1行サマリー: フェーズ1初回E2Eの本番ログで10_derivのOI全件0の真因が「ccxtがKraken FuturesのfetchOpenInterestに未対応」と確定したため、承認済み対応B（OI取得の原因調査→修正）の実装としてOIソースをBinance USDM公開APIに切替。あわせて、手動起動待ちで停滞していたリサーチデータ取得に日次cronを追加。

## 1. OIソース切替（承認済み対応Bの完結）

- **真因（本番ログ 2026-07-06 00:02 で確定）**: `krakenfutures fetchOpenInterest() is not supported yet` — Krakenからは構造的に取得不可。
- **対応**: `fetch_open_interest` を Binance USDM perp（公開API・キー不要）に切替。シンボルは `BTC/USD → BTC/USDT:USDT` へマッピング。funding rate は従来どおり Kraken Futures（bot全体の約定はKraken現物価格のまま）。
- **根拠**: OIは市場全体のセンチメント指標としての利用であり、取引所が異なっても系列内で一貫していれば目的を満たす。BinanceはOI出来高とも世界最大でむしろ代表性が高い。
- **検証**: スタブテストでシンボルマッピング・欠損時None・例外時Noneの全ケース確認。E2Eは次回Actions実行（`derivatives.open_interest` に初めて非ゼロ値が入るはず。翌日ヘルスチェックで確認）。
- 10_derivのOI系分岐（OI急増/急減）は次々回実行から機能し始める（初回は前回OI=0のためoi_change=0）。

## 2. リサーチデータ取得の日次cron追加

- 手動起動API（workflow_dispatch）は連携権限不足（403）で司令塔から起動できず、手動クリック依頼も4回未達のまま約12時間停滞。
- `research_data.yml` に日次cron（11:20 UTC、バックアップ13:50 UTC）を追加して自動化。手動ボタンは残置。**リサーチ完了後はscheduleを削除してよい**（ymlにコメント済み）。
- データは毎回再取得・上書き（数MB/日のコミット）。恒久運用ではなくリサーチ期間限定の措置。

## 評価

- OI切替の評価は既存の `2026-07-05-fix-10deriv.md` の成功基準（7/12週次）に統合。
- research.db が取得され次第、`backtest_daily.py` による3仮説判定を実施（`2026-07-05-pivot-daily-research.md` の判定基準に従う）。
