# eos-mcp

[Arista EOS](https://www.arista.com/en/products/eos) 機器を eAPI（`pyeapi`）経由で操作する MCP サーバ。

大きく2つの用途を想定している。ひとつは複数台まとめての朝の `daily_brief`（環境・errdisabled インターフェース・稼働時間・MLAG・直近の syslog アラート）、もうひとつは 1 台を見る・変更する場面で使う運用ツール群（show コマンド実行、running-config 取得・差分表示、コミットタイマー付きの設定投入）。

## 領域別ツール一覧

| 領域 | ツール |
|---|---|
| インベントリ | `get_router_list`、`get_device_facts`、`get_device_facts_batch`、`get_version` |
| コマンド実行 | `run_command`、`run_commands`、`run_command_batch`、`run_commands_batch` |
| 設定 | `get_config`、`get_config_diff`、`list_config_sessions`、`push_config`、`confirm_config_session`、`abort_config_session` |
| 診断 | `collect_tech_support` |
| 朝のパトロール | `health_check`、`daily_brief` |

**3 つのツールがガード付きで機器の状態を変更する:** `push_config`・`confirm_config_session`・`abort_config_session`。**`run_command` とそのバッチ系・複数コマンド系は、ガードの無いもう一つの書き込み経路。** サーバー側は `show ...` 系コマンドに制限しておらず、`configure terminal ...` や `reload` もそのまま実行できる。それぞれを何が抑止しているかは [リファレンス](reference.md) を参照。

## 設計上の要点

**認証情報の保管場所はローカルファイルのみ。** 環境変数に平文でユーザ名・パスワードを渡す方式ではなく、eos-mcp は `config.ini`（`[DEFAULT]` セクション + 機器ごとの `[hostname]` セクション）を読み込み、そこに実際の eAPI ユーザ名・パスワード・トランスポート・`verify` 設定を持たせている。`health_check` の設定状態確認を除く全ツールが、解決済みパス（`EOS_MCP_CONFIG` → `./config.ini` → `~/.config/eos-mcp/config.ini`）に実データの入った `config.ini` を要求し、無ければ動かない。

**`push_config` はデフォルトで dry-run。** 名前付きの `configure session` を開いて `config_lines` を投入し、呼び出し側が明示的に `dry_run=False` を指定しない限り差分を表示してセッションを中断する（commit しない）。実際に投入する場合は `commit timer` を使うので、`confirm_config_session` で確定しないまま放置されたセッションは自動的にロールバックされる。

**TLS 互換性は意図的なパッチであり、放置された回避策ではない。** EOS 4.28.x を Python の厳格化されたデフォルト TLS ポリシー（特に Python 3.14）から叩くと `SSLV3_ALERT_HANDSHAKE_FAILURE` が発生しうる。eos-mcp はインポート時に SSL コンテキストへパッチを当て（`SECLEVEL=0`、最低 TLS 1.0）、古い機器への到達性を確保している。`config.ini.example` の `verify = false` も同じ理由による既定値。

## 次に読むもの

- [セットアップ](setup.ja.md) — インストール、`config.ini`、環境変数、MCP クライアントへの登録
- [リファレンス](reference.ja.md) — 全ツール、書き込みツールの権限ゲート、CLI、終了コード
