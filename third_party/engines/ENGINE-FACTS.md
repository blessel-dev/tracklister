# Engine facts (E-0), confirmed from the pinned sources and binaries

Sources inspected: the tag archives `v3.0.5` and `v2.6.0` of https://github.com/fiso64/sockseek
(downloaded by `tools/fetch_engine.py` into `third_party/engines/bin/src/`). Paths below are
relative to the archive roots: `sockseek-3.0.5/` and `sockseek-2.6.0/slsk-batchdl/`.
Binaries were run ONLY with `--help`/`--version` (outputs in `tests/fixtures/engine/help-*.txt`,
`version-*.txt`) and once each in MOCK mode after item 6 was proven
(`tests/fixtures/engine/mock_probe/probe_mock_run.py`, outputs in `tests/fixtures/engine/mock-run/`).

## Pins

| id | asset | SHA-256 (GitHub API `digest`, verified) | exe | licence |
|---|---|---|---|---|
| sockseek-3.0.5 | `sockseek_3.0.5_win-x64.zip` (50.4 MB; `sockseek.exe` + `LICENSE` at zip root) | `1b5c1189dcfc24cc9fea22dc67a58b7a5f0a127d0367355cf2a8718100044802` | `sockseek.exe`, `--version` prints `3.0.5` | AGPL-3.0 |
| sldl-2.6.0 | `sldl_win-x86_self-contained.zip` (10.5 MB; `sldl.exe`, `sldl.pdb`, `LICENSE`) | `6e39232c8c22f9b4e5f6a635dae85fdc405e50bcc56392351001d8964cf29a63` | `sldl.exe`, `--version` prints `2.6.0.0` | GPL-3.0 |

Deviation from the plan: 2.6.0 has no win-x64 asset. The API lists `sldl_win-x86.zip`
(framework-dependent) and `sldl_win-x86_self-contained.zip`; the self-contained x86 build is pinned
(runs on x64 Windows, no .NET install).

## Command line (both dialects; validated by the mock runs, `mock-run/*/argv.txt`)

| Topic | 3.0.5 | 2.6.0 |
|---|---|---|
| `--help`/`--version` exit before anything else | `Sockseek.Cli/Program.cs:26`, `Sockseek.Cli/Help.cs:42-63` | `Program.cs:7`, `Help.cs:46-56` |
| no config | `--no-config` (`Sockseek.Cli/Services/ConfigManager.cs:39,298,488`) | `--no-config` (`Config.cs:225,799`) |
| login | `--user`, `--pass` (`ConfigManager.cs:493-496`) | same (`Config.cs:845-851`) |
| output dir | `--output-dir`; `-p`/`--path` are aliases; `-o` = output dir and rejects numeric values (`ConfigManager.cs:563-567`, `:1467-1478`) | `-p`/`--path` (`Config.cs:789-791`); `-o` = offset |
| share count | `--no-modify-share-count` exists (hidden; `ConfigManager.cs:521-522`); when set the client never calls `SetSharedCountsAsync` (`Sockseek.Core/Soulseek/SoulseekClientManager.cs:377-381`); default otherwise announces `--shared-files/--shared-folders` (0/0) | `--no-modify-share-count` (`Config.cs:1301`); without it the client announces 50 folders / 1000 files (`Services/SoulseekClientManager.cs:165-169`) |
| concurrency | `--concurrent-jobs` (`ConfigManager.cs:511`) | `--concurrent-downloads` (`Config.cs:1089`) |
| unknown option | usage error, exit 2 (`ConfigManager.cs` `UnknownArgument`) | `InputError` -> exit 1 (`Config.cs:1472,1536`) |
| values starting with `-` | a separate token `-abc` is expanded to `-a -b -c`; `--flag=value` keeps it (`ConfigManager.cs:1236-1260`, `Next()` `:1381-1395`) | same expansion (`Config.cs:153-167`, `-abc`: `:164`, `--arg=val`: `:160`) |

Decision taken from this table: the adapter passes `--no-modify-share-count` to BOTH dialects
(the brief's "honest mode"; the plan's 3.x substitute `--shared-files 0 --shared-folders 0` was based
on the flag missing from the help, but the 3.0.5 source accepts it). Credentials whose value starts
with `-` are passed as `--user=<v>` / `--pass=<v>`.

## CSV input

- Columns by alias; `id`/`url`/`uri` columns become a URL column (3.0.5 `Sockseek.Core/Extractors/Csv.cs:97`;
  2.6.0 `Extractors/Csv.cs:97`): never written.
- `{snum}` = 1-based data-row number (`Csv.cs:197-201` in 3.0.5, `Csv.cs:156` in 2.6.0); `{row}` = file line.
- Empty `Length`: warning `Couldn't parse track length "" with format "s"` and unknown length
  (3.0.5 `Csv.cs:182`; seen in both mock runs).
- Quoted fields with commas and doubled quotes parse correctly in both engines (mock row 6 and 7).

## 5. name-format appends the extension

`--name-format "{snum}/{slsk-filename}"` -> `in/<snum>/<soulseek file name><ext>`: the engine adds
`Path.GetExtension(downloadPath)` itself (3.0.5 `Sockseek.Core/Files/FileManager.cs:260`, 2.6.0
`Services/FileManager.cs:106`). Mock runs: `in/4/Same Name.flac` and `in/5/Same Name.flac` (two rows
with the same Soulseek file name never collide). 3.0.5 downloads into
`in/.sockseek-staging/<guid>/<name>.incomplete` first; collect only `in/<snum>/*`, ignore
`.sockseek-staging` and `*.incomplete`.

## 2. Index file (`--index-path`)

Same CSV in both: header `filepath,artist,album,title,length,tracktype,state,failurereason`
(3.0.5 `Sockseek.Core/Files/M3uEditor.cs:375`, 2.6.0 `Services/M3uEditor.cs:311`). `filepath` is
relative to the index folder with a `./` prefix (3.0.5 `./in/1/x.flac`, 2.6.0 `./in\1\x.flac`), empty
when nothing was downloaded; length `-1` = unknown; fields with `,` or `"` are quoted.

| state | 3.0.5 `JobStateOld` (`Common/Enums.cs:83`) | 2.6.0 `TrackState` (`Enums.cs`) |
|---|---|---|
| 0 | Pending | Initial |
| 1 | Done | Downloaded |
| 2 | Failed | Failed |
| 3 | AlreadyExists | AlreadyExists |
| 4 | NotFoundLastTime | NotFoundLastTime |

| reason | 3.0.5 `JobFailureReason` (`Common/Enums.cs:92`) | 2.6.0 `FailureReason` |
|---|---|---|
| 0 | None | None |
| 1 | InvalidSearchString | InvalidSearchString |
| 2 | OutOfDownloadRetries | OutOfDownloadRetries |
| 3 | (legacy: read as NoMatchingResults) | NoSuitableFileFound |
| 4 | AllDownloadsFailed | AllDownloadsFailed |
| 5 | Other | Other |
| 6 | ExtractionFailed | - |
| 7 | Cancelled | - |
| 8 | ChildJobsFailed | - |
| 9 | NoSearchResults | - |
| 10 | NoMatchingResults | - |

Playlist (`--write-playlist --playlist-path`): one relative path per downloaded row (backslashes)
or `#FAIL: <Artist - Title> [<ReasonName>]` (3.0.5 `M3uEditor.cs:413`, 2.6.0 `M3uEditor.cs:346`).

## 1. `--no-progress` stdout lines (stdout redirected = plain mode)

3.0.5 (`Sockseek.Cli/Utilities/CliProgressReporter.cs:828`, labels in `CliJobStatusPresenter.cs:59-115`;
real lines in `mock-run/sockseek-3.0.5/stdout.txt`):

```
[003] SongJob: searching: Fjaak - Spirit
[003] SongJob: downloading: Fjaak - Spirit: <peer>\..\Music\Fjaak\Fjaak - Spirit.flac
[003] SongJob: succeeded: Fjaak - Spirit: <peer>\..\Music\Fjaak\Fjaak - Spirit.flac
[005] SongJob: failed [No search results]: Nobody Known - Nonexistent Track
    Error: No Soulseek file results found.
[cli] Completed: 5 succeeded, 2 failed.
```

The `[NNN]` is the engine's job display id (extract job and job list come first), NOT the CSV item
number: the adapter maps a line to its row by the `Artist - Title` text it sent. Other labels:
`timed out`, `rate limited`, `waiting search`, `already exists`, `not found`, `cancelled`.
Ban/kick: 3.0.5 logs `Soulseek server kicked this client, probably because the same account logged
in elsewhere. Stopping this run.` (`SoulseekClientManager.cs:26-27,95`); there is no dedicated
"search ban" message in either engine.

2.6.0 (`Services/Searcher.cs:52,115,247`, `Models/DownloadWrapper.cs:44,116`; real lines in
`mock-run/sldl-2.6.0/stdout.txt`): `Searching: <Artist - Title> (<len>s)`, `Initialize: <peer>\..\<file> [<info>]`,
`<State>:` padded to 14 columns + ` <peer>\..\<file> [...]` where State is the transfer state
(`Succeeded`, `TimedOut`, `Errored`, `Rejected`, `Cancelled`, `Aborted`; the mock client reports
`None`), `Not found: <Artist - Title>`, `Waiting: <...>` (rate limiter),
`Completed: N succeeded, M failed.`

Both engines print the LOGIN USERNAME: 3.0.5 `Logging in as <user>..` (`SoulseekClientManager.cs:372`),
2.6.0 `Login <user>` (`Services/SoulseekClientManager.cs:151`, seen in the mock run). The password
is never printed (checked in both mock runs). The runner redacts the username from stdout and
rewrites `engine.log` redacted after every run.

## 3. Exit codes

- 3.0.5 (`Sockseek.Cli/Program.cs:14-20,746-761`): 0 success; 1 = at least one item failed or an
  infrastructure failure (mock run: 5 ok + 2 not found -> exit 1); 2 usage error; 130 cancelled.
- 2.6.0: `Main` returns `Task` (exit 0 even when items fail; mock run -> 0); `InputError` -> 1
  (`Config.cs:1536`); an unhandled exception (e.g. login failure) -> .NET crash code (non-zero).
- So the exit code is never the per-row truth: the files under `in/<snum>/` are.

## 4. `--print json-all`

One JSON array on one line (3.0.5 `Sockseek.Cli/Utilities/JsonPrinter.cs:28-63,174-193`; 2.6.0
`Utilities/JsonPrinter.cs`), `[]` when empty:

```json
[{"User":{"Username":"local","UploadSpeed":9.5E-05,"HasFreeUploadSlot":true},
  "File":{"Length":20,"Filename":"peerA\\Music\\Fjaak\\Fjaak - Spirit.flac","Size":3131685,
          "Bitrate":1250,"SampleRate":44100,"BitDepth":16}}]
```

`Length`, `Bitrate`, `SampleRate`, `BitDepth` are omitted when unknown. 3.0.5 lists only results
that pass the required conditions; 2.6.0 also listed the 31 s remix that fails `--length-tol 3`.
Keyed string input `artist=A, title=T, length=L` is a song search in both
(3.0.5 `Sockseek.Core/Extractors/String.cs:16-21,90-160`).

## 6. Mock mode never touches the network (proof)

- 3.0.5: `SoulseekClientManager.CreateClientInstance` returns `LocalFilesSoulseekClient` when
  `--mock-files-dir` is set (`Sockseek.Core/Soulseek/SoulseekClientManager.cs:280-288`); the real
  `Soulseek.SoulseekClient` is constructed only in the other branch (`:294`). Its `ConnectAsync`
  and `SetSharedCountsAsync` are no-ops (`LocalFilesSoulseekClient.cs:127-140`). The only other
  outbound code paths are the Bandcamp/MusicBrainz/YouTube extractors (`Extractors/*.cs`, not used
  for `--input-type csv`/`string`), `--remote` (`RemoteCliBackend.cs:29`) and `--yt-dlp`; none is passed.
- 2.6.0: `CreateClientInstance` returns `Tests.ClientTests.MockSoulseekClient` when
  `mockFilesDir` is set (`Services/SoulseekClientManager.cs:86-89`; that class is compiled into
  sldl.exe by `slsk-batchdl.csproj`), real client only at `:129`; mock `ConnectAsync`/
  `SetSharedCountsAsync` are no-ops (`slsk-batchdl.Tests/TestClients/MockSoulseekClient.cs:87-99`).
- Therefore each binary was run once in mock mode with dummy credentials, `--no-config`, a temp
  mock dir and (3.0.5) `--no-listen`. No real account was used and no Soulseek connection exists
  in that code path.
