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
1. `EOS_MCP_CONFIG` 環境変数
2. `./config.ini`（カレントディレクトリ）
3. `~/.config/eos-mcp/config.ini`

（個々のMCPツール呼び出しでは、`config_path`パラメータでパスを上書きすることも可能）

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

## 開発

### ライブスモークテスト

ユニットテストはフィクスチャに対してロジックを検証するだけで、ツールが実データを
返さなくなったことは検出できない。`scripts/smoke_test.py` は設定済みの機器に対して
**登録されている全ツール**を実行し、空・不正・エラー応答を失敗として報告する。

```bash
# サーバーと同じインベントリファイル（EOS_MCP_CONFIG）を使う
uv run python scripts/smoke_test.py
uv run python scripts/smoke_test.py --only facts --traceback
```

- **読み取り専用**。`push_config`・`confirm_config_session`・`abort_config_session` は
  名前で除外する（テストで強制）。`collect_tech_support` も除外する — 機器を変更しないが、
  ここでの検証に使わない出力のために機器 CPU を数分間占有するため。コマンド実行系ツールは
  `show version` で検証する。これらは enable モードのコマンドを一般に受け付けるので、
  スモークテストが重大なコマンドを打つ主体になってはならない。
- **レポートにペイロードを出さない**。ツール名とステータスのみ。エラー文言は必ず
  機器名を含み、ペイロードは設定そのものなので伏字にする。
- **機器固有の値を spec に書かない**。ホスト単位のツールが必要とする機器名は、設定済み
  インベントリから実行時に発見し、空ならスキップする。2本のテストで担保: 該当パラメータの
  直値を拒否し、アドレス的な形がファイル内に現れることを禁じる（公開リポジトリのため）。
- 各 probe は、これらのツールが例外の代わりに返す `Error (<host>): ...` 行を必ず拒否する。
  さもないと到達不能な機器が「成功」として通ってしまう。
- CI では安価な半分を強制する。probe spec の無いツールを登録するとビルドが失敗するので
  （`tests/test_smoke_probes.py`）、ツール追加時に「どうやって動作を確認するか」を必ず決めることになる。
- `scripts/smoke_harness.py` はエンジンであり EOS 固有の知識を持たない。このハーネスを
  共有する各サーバーで同一に保つ方針なので、エンジンのバグはこの写しを直すのではなく
  一度直して全体に同期する。

## ライセンス

Apache-2.0
