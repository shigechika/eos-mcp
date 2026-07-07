# eos-mcp

Arista EOS 機器を eAPI 経由で操作する MCP サーバ。

show コマンド実行、running-config 取得、configure session を使った設定投入（コミットタイマー付き）、tech-support 収集などを MCP 対応 AI アシスタントに提供します。

## インストール

```bash
pip install eos-mcp
```

## 設定

`config.ini.example` を `~/.config/eos-mcp/config.ini` にコピーし、認証情報を記入してください。

```ini
[DEFAULT]
username = admin
password = yourpassword
transport = https
verify = false

[switch1.example.com]
tags = main,dc1

[switch2.example.com]
tags = main,dc1
```

設定ファイルの探索順:
1. `--config_path` 引数
2. `EOS_MCP_CONFIG` 環境変数
3. `./config.ini`（カレントディレクトリ）
4. `~/.config/eos-mcp/config.ini`

## 使い方

```bash
# 設定確認と機器一覧表示
eos-mcp --check

# 特定ホストへの疎通確認
eos-mcp --check --check-host switch1.example.com

# MCP サーバ起動（stdio トランスポート）
eos-mcp
```

## ツール一覧

| ツール | 説明 |
|---|---|
| `health_check` | サーバのバージョンと設定状態を報告（軽量・機器には接続しない） |
| `get_router_list` | 登録済み機器を一覧表示（タグフィルタ対応） |
| `get_device_facts` | 1 台の機器情報を取得（モデル・シリアル・EOS バージョン・稼働時間・メモリ） |
| `get_device_facts_batch` | 複数台の機器情報を並列取得 |
| `get_version` | EOS バージョン文字列を返す（疎通確認用） |
| `run_command` | 1 台の機器で enable モードコマンドを 1 つ実行 |
| `run_commands` | 1 台の機器で enable モードコマンドを複数実行 |
| `run_command_batch` | 複数台の機器で enable モードコマンドを並列実行 |
| `get_config` | running-config を取得 |
| `get_config_diff` | ロールバックチェックポイントとの設定差分を表示 |
| `list_config_sessions` | configure session の一覧と状態を表示 |
| `push_config` | configure session 経由で設定を投入（デフォルトは dry_run=True） |
| `confirm_config_session` | commit timer 待ちのセッションを確定 |
| `abort_config_session` | 保留中のセッションを中断 |
| `collect_tech_support` | show tech-support を収集 |
| `daily_brief` | 複数台のヘルスチェック（環境・errdisabled・稼働時間・メモリ・MLAG・直近 syslog アラート） |

## 要件

- Python >= 3.10
- Arista EOS（eAPI 有効化済み: `management api http-commands`）
- 対象機器のポート 443（HTTPS）への到達性

## TLS 互換性（EOS 4.28.x + Python 3.14）

EOS 4.28.x と Python 3.14 の組み合わせで `SSLV3_ALERT_HANDSHAKE_FAILURE` が発生する場合、eos-mcp は自動的にレガシー TLS を有効化するパッチを適用します。

## 設定投入の安全機構

`push_config` は以下の安全機構を備えています:

- **dry_run モード**（デフォルト）: `configure session` を作成して差分を確認するだけで、commit しません
- **コミットタイマー**: 実投入時は `commit timer` でタイムアウトを設定。`confirm_config_session` で確定するまで自動ロールバック
- **セッション管理**: `list_config_sessions` で現在のセッション状態を確認、`abort_config_session` でいつでも中断可能

## ライセンス

Apache-2.0
