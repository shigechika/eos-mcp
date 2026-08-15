# リファレンス

## `health_check()`

呼び出しごとに必ず 7 個のキーが返る:

| キー | 意味 |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | 常に `eos-mcp` |
| `version` | パッケージバージョン |
| `config_path` | 解決済みの `config.ini` パス（読み込みに失敗した場合でも、どこを探したか分かるよう設定される） |
| `device_count` | 見つかった `[hostname]` セクション数 |
| `tags` | 全機器の `tags =` 値をまとめてソート・重複排除したもの |
| `config` | `ok` / `error` / `missing` |

`detail` は `degraded` または `error` のときのみ追加され、理由（ファイル不在、または `config.ini` のパースエラー）を含む。

軽量に作られている: `config.ini` の読み込み・パースだけを行い、EOS 機器への eAPI/pyeapi 接続は**行わない**。そのため大規模フリートに対しても、ネットワークに触れずに安全に呼び出せる。他のツールはすべて、解決済みパスに実データの入った `config.ini` を必要とする。

## ツール索引

| ツール | 用途 |
|---|---|
| `get_router_list(tags=None)` | `config.ini` に登録済みの機器一覧（タグでフィルタ可能） |
| `get_device_facts(hostname)` | モデル・シリアル・EOS バージョン・ハードウェアリビジョン・稼働時間・メモリ・MAC・アーキテクチャ |
| `get_device_facts_batch(hostnames=None, tags=None, max_workers=5)` | 複数機器の同様の情報を並列取得 |
| `get_version(hostname)` | モデル + EOS バージョン（疎通確認用） |
| `run_command(hostname, command)` | **無制限。** 1 台で enable モードコマンドを 1 つ実行 |
| `run_commands(hostname, commands)` | **無制限。** 1 台で enable モードコマンドを複数実行 |
| `run_command_batch(command, hostnames=None, tags=None, max_workers=5)` | **無制限。** 複数機器で 1 コマンドを並列実行 |
| `run_commands_batch(commands, hostnames=None, tags=None, max_workers=5)` | **無制限。** 複数機器で複数コマンドを並列実行 |
| `get_config(hostname)` | running-config を取得 |
| `get_config_diff(hostname, rollback_id=1)` | running-config と N 番目のロールバックチェックポイントとの差分 |
| `list_config_sessions(hostname)` | configure session の一覧と状態（pending / pendingCommitTimer / completed） |
| `push_config(hostname, config_lines, session_name="mcp-push", dry_run=True, commit_timer=300)` | **書き込み。** configure session 経由で設定を投入。デフォルトは dry-run |
| `confirm_config_session(hostname, session_name="mcp-push")` | **書き込み。** commit timer 待ちのセッションを確定 |
| `abort_config_session(hostname, session_name="mcp-push")` | **書き込み。** 保留中のセッションを破棄 |
| `collect_tech_support(hostname)` | `show tech-support` を収集（大きな出力、30 秒以上かかる） |
| `daily_brief(hostnames=None, tags=None, max_workers=5, since_hours=24)` | 複数台の朝のヘルスチェック: 環境・errdisabled インターフェース・稼働時間・MLAG・直近の syslog アラート |

「無制限」と記したツールは、任意の enable モードコマンドをそのまま実行する。実運用上の意味と何が抑止しているかは [セットアップ](setup.ja.md) の「状態を変えるツール」を参照。

## `daily_brief`

解決済みの全機器に対して並列で `check_health()` を実行し、1 つの Markdown レポートにまとめる: 機器ごとの `CRITICAL` / `WARNING` / `OK` ステータス（環境センサー・errdisabled インターフェース・MLAG 状態・メモリ、および直近 `since_hours` 時間以内の BGP/OSPF/STP/LACP/MLAG/リンクダウン系 syslog アラート）に続き、フリート全体のサマリー件数を出力する。接続に失敗した機器は、レポートから黙って除外されるのではなく、その機器の行が `CRITICAL: connection failed` として表示される。

対象は `hostnames`・`tags`、またはその両方から解決する。どちらも指定しなければ `config.ini` の全機器が対象になる。

## `get_config_diff`

`rollback_id=1`（デフォルト）は最新のロールバックチェックポイントとの差分。値を大きくするほどより過去のチェックポイントと比較する。startup-config との差分表示には EOS 4.30 以降が必要——それより古いリリースでは適切にフォールバックする。

## CLI

```bash
eos-mcp                              # MCP サーバを起動（stdio、デフォルト、引数なし）
eos-mcp -V | --version                # バージョンを表示して終了
eos-mcp -h | --help                   # 使い方を表示
eos-mcp --check                       # config.ini を検証し機器一覧を表示して終了
eos-mcp --check --check-host HOST     # HOST への eAPI 接続も試す
```

`--check` / `--check-host` の終了コード: `0` 成功、`1` 設定エラー（`config.ini` が無い、またはパースできない）、`2` ホスト接続エラー（config に無いホスト、または eAPI 呼び出し自体の失敗）。

## TLS 互換性

EOS 4.28.x と、Python の厳格化されたデフォルト TLS ポリシー（特に Python 3.14）の組み合わせでは `SSLV3_ALERT_HANDSHAKE_FAILURE` が発生しうる。eos-mcp はインポート時に SSL コンテキストへパッチを当て（`SECLEVEL=0`、最低 TLS 1.0）、運用側が何もしなくても古い機器へ到達できるようにしている。`config.ini.example` の `verify = false` も同じ理由による既定値——多くの現場では内部の自己署名証明書で eAPI を運用しているため。
