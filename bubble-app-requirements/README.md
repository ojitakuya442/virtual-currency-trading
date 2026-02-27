# Bubble アプリ 要件定義リポジトリ

## 概要

このリポジトリは、Bubble（ノーコードプラットフォーム）で開発するアプリケーションの要件定義を管理するためのものです。

## ディレクトリ構成

```
bubble-app-requirements/
├── README.md                          # このファイル
├── docs/
│   ├── 01-project-overview.md         # プロジェクト概要
│   ├── 02-functional-requirements.md  # 機能要件
│   ├── 03-non-functional-requirements.md # 非機能要件
│   ├── 04-data-model.md               # データモデル定義
│   ├── 05-screens.md                  # 画面定義
│   ├── 06-workflows.md                # ワークフロー定義
│   ├── 07-user-stories.md             # ユーザーストーリー
│   └── 08-api-integrations.md         # API連携
└── .gitignore
```

## ドキュメント一覧

| ドキュメント | 内容 | ステータス |
|------------|------|----------|
| [プロジェクト概要](docs/01-project-overview.md) | 目的・ターゲット・スコープ | 📝 作成中 |
| [機能要件](docs/02-functional-requirements.md) | 必須機能・オプション機能 | 📝 作成中 |
| [非機能要件](docs/03-non-functional-requirements.md) | パフォーマンス・セキュリティ等 | 📝 作成中 |
| [データモデル](docs/04-data-model.md) | データタイプ・フィールド定義 | 📝 作成中 |
| [画面定義](docs/05-screens.md) | ページ・UI コンポーネント | 📝 作成中 |
| [ワークフロー](docs/06-workflows.md) | Bubble ワークフロー定義 | 📝 作成中 |
| [ユーザーストーリー](docs/07-user-stories.md) | ユーザー視点の要求 | 📝 作成中 |
| [API 連携](docs/08-api-integrations.md) | 外部 API・プラグイン | 📝 作成中 |

## 使い方

1. 各ドキュメントを順番に記入する
2. 変更は随時コミットして管理する
3. レビュー後に `main` ブランチへマージする

## ステータス凡例

- 📝 作成中
- ✅ 完了
- 🔄 レビュー中
- ⏸ 保留
