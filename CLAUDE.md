# CLAUDE.md

仮想通貨自動売買Bot（**ペーパートレード** — 実売買は行わない）。10種類の戦略botを GitHub Actions 上で15分間隔で並行稼働させ、成績を比較検証するプロジェクト。

## 司令塔として作業する場合（最重要）

パフォーマンスレビュー・パラメータ調整・インシデント対応・bot稼働管理を依頼されたら、**必ず先に `docs/opus-command-center-spec.md` を読む**こと。そこに業務別ランブック（§6）、bot判定の数値基準（§7）、禁止事項（§8）、レポート書式（§9）が定義されている。

- 判定は必ず §7 の数値基準で行う。基準に該当しないbotは変更しない。
- パラメータ変更は 1回1bot・最大2パラメータ・評価期間7日（§6.3）。
- リスク管理値の緩和・データ削除・実売買化は人間の承認必須（§8）。
- 判断はすべて `docs/decisions/` に記録する。

### 作業の進め方（Opus向け運用指針）

- **分析を始めるときは必ず** `docs/dashboard.json` を読む。詳細が必要になったときだけ `data/trading_bot.db` をクエリする。
- **判断・変更を行う前に必ず** `docs/decisions/` で同種の過去判断を確認し、作業後は結果をそこへ記録する。
- 軽微な選択（命名・クエリの書き方・文言）は質問せず妥当な案で進めてよい。確認が必要なのは §8 のガードレール事項・スコープ変更・破壊的操作のみ。
- 異常やバグの候補は、確信度が低くても重要度を付けて全て列挙する。絞り込みは §7 の判定テーブルで行う。
- 進捗・完了の報告は、そのセッションで実行したコマンドやクエリの結果を根拠にできるものだけにする。

## アーキテクチャ

```
.github/workflows/
  collect_and_trade.yml   # 15分間隔: 価格取得→10botシグナル→仮想約定→DBコミット
  notify_hourly.yml       # 毎時: Discord通知 + docs/dashboard.json 更新
  daily_report.yml        # 毎日21:17 JST: 日次レポートをDiscordへ
  initial_setup.yml       # 手動: ヒストリカル取得 + ML事前学習
scripts/run_bots.py       # メイン実行（Actionsのエントリポイント）
src/config.py             # 全設定。BOT_CONFIGS に10botの全パラメータ
src/bots/bot_01〜10_*.py  # 各戦略（Donchian, EMA+ADX, BB, VWAP, Squeeze, 出来高モメンタム, ペアトレ, レジーム, MLゲート, デリバ）
src/simulator.py          # target_position 方式の仮想約定エンジン
src/database.py           # SQLite (prices / trades / balances / bot_state)
data/trading_bot.db       # 稼働データ（Actionsがコミットで更新。削除禁止）
docs/dashboard.json       # 毎時更新の集計データ。分析はまずここを見る
docs/opus-command-center-spec.md  # 司令塔仕様書
docs/decisions/           # 司令塔の判断ログ
web/                      # Next.js ダッシュボード
```

## 主要な事実

- 取引所: Kraken 公開API（キー不要）/ 銘柄: BTC・ETH・SOL の対USD
- 各bot初期資産 50,000円、PnL計算は USD/JPY=150 固定
- 取引コスト: 片道0.15%（手数料0.1% + スリッページ0.05%）
- ロングのみ（position 0.0〜1.0）。サーキットブレーカー: 資産20%減で自動停止
- 15分間隔だが足は5分足（`INTERVAL = "5m"`）

## コマンド

```bash
pip install -r requirements.txt
python scripts/run_bots.py            # bot一括実行（ローカル動作確認に使う）
python scripts/send_daily_report.py   # 日次レポート送信（要 DISCORD_WEBHOOK_URL）
python src/export_dashboard.py        # dashboard.json 再生成
sqlite3 data/trading_bot.db           # DB直接分析
```

## 作業上の注意

- `data/*.db` と `models/` は Actions が自動コミットする。手動編集・削除しない。
- 価格データの欠損は仕様上「取引なし」で正常。遡及補完しない。
- パラメータ変更は `src/config.py` の `BOT_CONFIGS` のみで行い、bot実装ロジックはバグ修正以外触らない。
- 変更後は `python scripts/run_bots.py` の完走をローカルで確認してからコミットする。
- コミット書式: `tune(<bot名>): <param> <before>→<after> — <理由>`（チューニング時）。
