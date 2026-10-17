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

macOS (1.1, Apple Silicon only) has its own pin table with Sockseek alone; see section 9.

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

## 7. Search variants and `--desperate` (1.0.1, R4)

Why his rows "Komplex aka Jeroen Search - Inject", "Vkn.modular - Hidden Reason" and "TR440 - Somewhen"
found nothing, and what the app does about it (`core/aliases.py`, `engine/csvwriter.py::row_variants`,
`EngineJob.desperate`). Paths as in the sections above (3.0.5 / 2.6.0 archive roots).

- **Query cleaning.** 3.0.5 `CleanSearchString` (`Sockseek.Core/Search/Searcher.cs:694-710`): lower case,
  then every character of `s_special` (`Sockseek.Core/Common/Utils.cs:439-449`) becomes a space. 2.6.0:
  `Services/Searcher.cs:925-945` with `Utilities/Utils.cs:377-386` (`;:'"|?!<>*/\[]{}()-–—&%^$#@+=`~_`).
  Neither set has `.` or `,`: `Vkn.modular` is sent as the word `vkn.modular`, `TR-440` as `tr 440`.
- **Strict filters are literal.** `--strict-title` looks in the file name without extension,
  `--strict-artist` in the whole path (3.0.5 `Sockseek.Core/Matching/Conditions/FileConditions.cs:268-283`).
  Both first turn `_` and `:|?><*"` into spaces, remove diacritics and collapse spaces (`:296-333`,
  `:381-390`), then need the text as written, with a boundary character on each side
  (`Common/Utils.cs:592-657`; for the title whitespace is skipped first, and a digit counts on the left:
  `04 Trip`). So `TR 440` is not in `TR-440 - Somewhen`, `Vkn modular` is not in `Vkn.modular - ...`, and
  `Komplex aka Jeroen Search` is not in `Jeroen Search - Inject`. That is why the app tries BOTH other
  spellings of a letter-digit name (`TR 440`, then `TR-440`) and each alias alone.
- **"No search results" also means "refused by the conditions".** The search options filter every file
  with the necessary conditions, strict filters included (3.0.5 `Searcher.cs:166-173`), and the count that
  decides `NoSearchResults` is the count of files that passed (`Searcher.cs:190`,
  `Transfers/Downloads/JobOrchestration/DownloadOutcomes.cs:23-24`). His «Sin resultados» rows may have had
  files that the strict artist refused.
- **The flag.** `-d`/`--desperate` in both: 3.0.5 `Sockseek.Cli/Services/ConfigManager.cs:742-743` (help
  `Sockseek.Cli/Help.Content.cs:106-107`), 2.6.0 `Config.cs:1304-1306` (help `Help.Content.cs:75-76`). A
  bool option: 3.0.5 takes the next token as its value only when it is `true`/`false`
  (`ConfigManager.cs:307-311`, `IsBoolLiteral` `:1265`), 2.6.0 when it does not start with `-`
  (`Config.cs:707-711`). The adapter passes the long form, bare, right before `--no-skip-existing`.
- **What it does.** Only when no file passed the conditions (3.0.5 `Searcher.cs:596-648`, 2.6.0
  `Services/Searcher.cs:739-811`): artist + album (CSV items have no album), artist + title without the
  length condition (only with a known length and a tolerance), then album, the title alone (title over 3
  characters) and the artist alone (artist over 3 characters). Every one of them forces
  `StrictTitle = StrictArtist = true` (`!ArtistMaybeWrong`, false for CSV input), also in a relaxed pass
  without `--strict-artist`, and drops only the length condition; formats, bitrate and banned users stay
  (a copy of the necessary conditions). With the base search and its no-diacritics twin (`:583-584`) that is
  at most 7 searches per item: `engine/runner.py::DESPERATE_SEARCHES_PER_ITEM`.
- **Rate limit.** Every search waits on a `RateLimitedSemaphore(searchesPerTime, renewTime)` (3.0.5
  `Searcher.cs:24,37`, `Search/RateLimitedSemaphore.cs:12-39`; 2.6.0 `Services/Searcher.cs:17,22`,
  `Utilities/RateLimitedSemaphore.cs:9-29`): a window that starts with the process and gives all its
  permits back at each renewal. The app's `SearchBudget.reserve()` spreads a reservation larger than one
  window the same way (34 now, 34 one window later...).
- **Mock-mode evidence** (`tests/fixtures/engine/mock_probe/probe_r4_variants.py`, outputs in
  `tests/fixtures/engine/mock-run-r4/<engine>/<run>/`, the safety proof of item 6; `--desperate` only adds
  searches through the mock client). The mock clients match each query word as a substring of the path
  (3.0.5 `Sockseek.Core/Soulseek/LocalFilesSoulseekClient.cs:199`, 2.6.0
  `slsk-batchdl.Tests/TestClients/MockSoulseekClient.cs:151-152`), so this shows the engines' own cleaning,
  filters and desperate searches, not how real peers match words. Mock files (invented folders):
  `Jeroen Search - Inject.flac`, `VKN Modular - Hidden Reason.flac`, `TR-440 - Somewhen.flac` (20 s each)
  and `Red Rooms - Trip.flac` (26 s, the row says 20). Both engines gave the same result:

  | Run | Rows sent | Found |
  |---|---|---|
  | 1-base (strict) | the 3 rows as written, Red Rooms - Trip (20 s), Nobody Real - Trip | nothing |
  | 2-variante-1 | Komplex, Vkn modular, TR 440 | `VKN Modular - Hidden Reason` (`TR 440` refused by `--strict-artist`) |
  | 3-variante-2 | Jeroen Search, TR-440 | `Jeroen Search - Inject`, `TR-440 - Somewhen` |
  | 4-desesperado (relaxed + `--desperate`) | the 5 rows of run 1 | only `Red Rooms - Trip` (6 s off); never the `Trip` of Red Rooms for Nobody Real; none of the 3 spelling rows |

  2.6.0 prints one `Searching:` line per search: 4 for each of the 3 rows, 2 for Red Rooms, 3 for the row
  without a length (`mock-run-r4/sldl-2.6.0/4-desesperado/stdout.txt`).
- **Fake engine.** `tests/fakes/fake_engine.py` accepts `-d`/`--desperate` and repeats these searches. With
  the network key `"engine_query_clean": true` it cleans the query and applies the strict filters like
  3.0.5; without it, the v1.0 word rules stay for the older scenarios.
  `tests/engine/test_r4_real_engine_mock.py` runs the four runs on it and gets the same files as the real
  engines, in both dialects.

## 8. Per-row download progress (1.0.1, R11)

The Estado cell of the Descarga screen shows what each row is doing and, while it downloads, a bar
(`engine/progress.py`, `gui/progress.py`). Mechanism chosen: **the plain `--no-progress` lines plus the
growing incomplete file**, in both engines. Sockseek's `--progress-json` was NOT adopted:

- With it, `Program.cs:221-227` attaches `JsonStreamProgressReporter` to the backend INSTEAD of the
  `CliProgressReporter`, so every plain line the adapter reads today disappears (row states, peer credit,
  fatal errors, bans, the redaction before anything is shown).
- Its byte events cannot be tied to a row: the backend path (`JsonStreamProgressReporter.cs`,
  `ReportDownloadProgress(DownloadProgressEventDto)`) writes only `jobId`, `bytesTransferred`, `totalBytes`
  and `percent`, and no other JSON event of that path carries a `jobId` (`ReportSearchStart`,
  `ReportDownloadStart` and `ReportStateChanged` write artist/title, user and file only). With 4 downloads at
  once the app could not know which row a byte count belongs to.
- One throttle for all jobs: `_lastDownloadProgressReport` is a single field (500 ms), so with several
  downloads most rows would get no update at all.

What the app reads instead:

- **Phase**: the lines already parsed (item 1): `searching`, 3.0.5 `queued (r)`/`queued (l)`/`initialising`
  (queued), the download start (3.0.5 `downloading:`, written by `Sockseek.Api/JobActivityLogFormatter.cs:305-319`;
  2.6.0 `Initialize:`, `Models/DownloadWrapper.cs:44`), `succeeded`, the not-found and failed lines. A second
  download start for the same row with another file is another copy (the bar starts again).
- **Bytes**: the size of the row's incomplete file, read every 0.5 s with a stat of its path (a directory
  listing reports a stale size while the engine writes). The file is never opened: a handle without delete
  sharing would make the engine's own rename of the finished file fail. 3.0.5 with `--name-format`
  downloads into `in/.sockseek-staging/<job id>/<file name>.incomplete`
  (`Sockseek.Core/Transfers/Downloads/Completion/OutputFinalizer.cs:47-48`, `Transfers/Downloads/Downloader.cs:85`)
  and opens it with `FileMode.Create` (shared for reading, `Downloader.cs:129`); 2.6.0 into
  `in/<file name>.incomplete` (`Services/FileManager.cs:23-45`, `Services/Downloader.cs:54`), then moves it to
  the name-format path. The file is matched by its name, the last part of the path the download line shows;
  two active rows downloading files with the same name get no bytes (never another row's bar).
- **Total**: 2.6.0 prints the size in its download display, `[<len>s/<rate><kbps>/<size>MB]` with one decimal
  (`Utilities/Printing.cs:20-29`), so its bar shows a percentage. 3.0.5's plain lines carry no size
  (`CandidateDisplayShort`, `Sockseek.Cli/Utilities/CliProgressReporter.cs:717-721`, path only; the live bars
  with the size are off in plain mode, `CliProgressReporter.cs:897-899`), so with the default engine the
  bar is indeterminate and the text says the MB received so far («Descargando 25,9 MB»).
- **2.6.0 lines name no query**: its `Initialize:` line goes to the one row of the pass that is searching
  and whose title words are all in the file name (`--strict-title` guarantees them); otherwise to none.
- Nothing new is written to disk and the progress events carry no peer name. The golden command lines
  do not change (`--no-progress` stays). The fake engine's `"write_s"` network key writes its files in
  steps where the real engines do (and adds the size to its 2.x `Initialize:` display, as the real one).

## 9. macOS (1.1, Apple Silicon only)

Facts from the GitHub Releases API of v3.0.5 and v2.6.0 and from a static reading of the downloaded
binaries (Mach-O headers, code signature, .NET bundle header); no macOS binary was ever run, on this
laptop or anywhere else (investigation report `02-informe-portabilidad.md`, 3.3; the archive listing and
headers were read again for 1.1, without extracting anything to disk).

| id | asset | bytes | SHA-256 (GitHub API `digest`, verified) | contents |
|---|---|---|---|---|
| sockseek-3.0.5 (macOS pin) | `sockseek_3.0.5_osx-arm64.tar.gz` | 46,570,010 | `6a18078b78f98a9797d723925574996a7bf87f6cc3012aee9efa1e9977a0edd0` | `LICENSE` (0644, 34,523 bytes) and `sockseek` (0755, 121,780,265 bytes, sha256 `d17bbd28d22c45c586b76826c9db6f9bb141f3a27dff975fa35e162dccf93163`), both at the archive's top level |
| sldl-2.6.0 (not shipped) | `sldl_osx-arm64.zip` | 10,675,172 | `3bf73d3063475df23c970c5be789445a8ced8d0874978fe27561945502fb1b32` | `sldl`, `sldl.pdb`, `LICENSE` |

- **sockseek**: a thin arm64 Mach-O (magic `cffaedfe`, cputype `0x0100000C`), minimum macOS 12.0, built
  with SDK 15.5. A .NET 10.0.9 single-file, self-contained bundle (342 entries, no separate native
  libraries, so it extracts nothing when it starts). Signed ad hoc by its author: CodeDirectory 0x20400,
  no Team ID, no hardened runtime; all 29,501 page hashes checked. The packager marks only `sockseek`
  executable (`Sockseek.Packager/Program.cs:14-17,63-65`).
- **How Tracklister uses it**: the .tar.gz travels unchanged in `Tracklister.app/Contents/Resources/engines/`.
  The app checks its size and SHA-256, extracts it with Python's `tarfile` and the `data` filter (no
  absolute paths, no `..`, no links out of the folder), sets 0755 on `sockseek` and runs only that copy,
  in `~/Library/Application Support/Tracklister/tools/engines/sockseek-3.0.5/` (`engine/spec.py`).
  Python never marks that copy with `com.apple.quarantine`, so Gatekeeper does not ask about it again.
- **Why sldl 2.6.0 stays out on macOS**: its Mac build has no code signature at all (no
  `LC_CODE_SIGNATURE`), and Apple Silicon kills unsigned arm64 code; its zip carries no executable bit
  (made on DOS, no Unix modes); and it runs on .NET 6, out of support since 12 Nov 2024. On macOS the
  engine selector shows only Sockseek, and a Windows `settings.json` that names sldl falls back to it.
- **Network**: as on Windows, there is no UPnP or NAT-PMP code in Sockseek (grep), so it sends no
  multicast to the local network.
