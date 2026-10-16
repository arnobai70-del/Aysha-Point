# Research (গবেষণা) অংশ: মালিকের নির্দেশিকা (রিলিজ 1.0.0)

মূল কথা:
- Research অংশ **ডিফল্টভাবে বন্ধ**। চালু না করলে কিছুই বদলায় না; scanner, ফোন অ্যালার্ট, capital, নিউজ সব 0.8.0-এর মতোই চলে।
- Research শুধু **পুরনো (ঐতিহাসিক) ডেটা জমিয়ে রাখে আর তার উপর নিয়মগুলো আবার চালিয়ে দেখে**। এটা কখনো READY দেয় না,
  ফোনে কিছু পাঠায় না, কোনো অর্ডার দেয় না। ট্রেড আগের মতোই আপনি নিজে Exness অ্যাপে নেবেন।
- এখনো **কোনো যাচাই করা trading edge নেই**। Research-এর ফল ভবিষ্যদ্বাণী নয়; ছোট নমুনা (১০০-এর কম বন্ধ ট্রেড) কিছুই প্রমাণ করে না।
- সব কমান্ড চলে PC-র `desktop` ফোল্ডার থেকে (Command Prompt): `python -m ayesha.cli research ...`

---

## ক. চালু করা আর অবস্থা দেখা

```
python -m ayesha.cli research status
python -m ayesha.cli research enable
```

**যা দেখা উচিত:** `status`-এ প্রথমে `State: OFF (legacy_only)`। `enable`-এর পরে `Research is ON (research-only)` আর লেখা থাকবে
যে scanner, strategy spec, READY/NO_TRADE নিয়ম, ফোন অ্যালার্ট আর capital ফাইল বদলায়নি।
সব research ফাইল থাকে শুধু `%USERPROFILE%\AyeshaFX\research\` ফোল্ডারে। কিছুই GitHub-এ যায় না।

## খ. ডেটা জমানো (ingest)

একবার জমানো ডেটা আর কখনো বদলায় না (frozen dataset)। নতুন করে নামালে সেটা নতুন dataset হয়, তাই পুরনো ফলের সাথে তুলনা ঠিক থাকে।

**পথ ১: OANDA practice থেকে সরাসরি** (install.bat-এ দেওয়া টোকেন দিয়ে; টোকেন PC থেকে বাইরে যায় না):
```
python -m ayesha.cli research ingest --provider oanda --pairs EURUSD,GBPUSD --days 730 --label "2 years"
```
`--days` না দিলে ১০৯৫ দিন (৩ বছর), `--pairs` না দিলে strategy-র ছয়টা পেয়ার, timeframe M15 আর M5। অনেক বছর আর অনেক পেয়ার
নামাতে কয়েক মিনিট লাগতে পারে।

**পথ ২: আগে নামানো CSV থেকে** (যেমন `backtest-local.bat` যে `data` ফোল্ডার বানায়):
```
python -m ayesha.cli research ingest --from-csv-dir "%USERPROFILE%\AyeshaFX\backtest\<তারিখ>\data" --label "backtest-local"
```
ফাইলের নাম হতে হবে `EURUSD_M15.csv`, `EURUSD_M5.csv` ধরনের।

**যা দেখা উচিত:**
```
Dataset ds_...: new, quality PASS
  EURUSD M15: ... bars, PASS, coverage ...%, missing ...
Next: ayesha research run baseline-sweep-mss-fvg --dataset ds_... --symbol EURUSD
```

Quality মানে:
- **PASS**: ব্যবহার করা যায়।
- **DEGRADED**: ফাঁক বা আটকে থাকা দাম আছে। আগে `inspect` দিয়ে দেখুন; রান করতে `--allow-degraded` লাগে, আর ফলে লেখা থাকে
  `DEGRADED_INPUT_DATA`।
- **REJECTED**: ভাঙা ডেটা (অসম্ভব দাম, এখনো শেষ না হওয়া candle, ভবিষ্যতের সময় ইত্যাদি)। শুধু দেখার জন্য রাখা হয়, কোনো রান চলে না।

ডেটা কখনো "মেরামত" করা হয় না: ফাঁক ভরানো, বানানো candle বা আন্দাজ করা দাম নেই। OANDA শুধু ASK close দেয়; ASK high/low
জানা নেই, তাই বানানো হয় না। CSV-তে ASK একেবারেই নেই (`ASK_UNKNOWN` তথ্য হিসেবে দেখায়, সমস্যা নয়)।
দাম OANDA-র, Exness-এর নয়; Exness-এর দাম আর spread আলাদা হতে পারে।

তালিকা আর বিস্তারিত:
```
python -m ayesha.cli research datasets
python -m ayesha.cli research inspect ds_...
```

## গ. Baseline রান (একই নিয়ম, পুরনো ডেটায়)

`baseline-sweep-mss-fvg` হলো লাইভ scanner-এর SWEEP_MSS_FVG নিয়ম, **একটুও না বদলে** (strategy 0.4.0, hash `9bb5e8ed5937`)।
```
python -m ayesha.cli research run baseline-sweep-mss-fvg --dataset ds_... --symbol EURUSD --split 2025-01-01
```
- `--split YYYY-MM-DD`: এই তারিখের আগে in-sample, পরে out-of-sample।
- `--mode m5confirm`: M5 confirmation সহ (dataset-এ M5 থাকতে হবে)। ডিফল্ট `m15`।
- `--folds 4`: walk-forward ভাগ (২–১২)।

**যা দেখা উচিত:** `Run run_...: COMPLETED`, তারপর signal আর বন্ধ ট্রেডের সংখ্যা আর limitation-এর তালিকা।
একই dataset আর একই সেটিংসে আবার চালালে **একই run id** আসে (নতুন করে হিসাব হয় না)। `--verify` যোগ করলে আবার হিসাব করে মেলায়:
`VERIFIED: the recomputed result has the same hash`।

Limitation-গুলো সবসময় পড়ুন:
| কোড | মানে |
|---|---|
| `HISTORICAL_SIMULATION_NOT_A_FORECAST` | পুরনো ডেটায় অনুশীলন, ভবিষ্যদ্বাণী নয় |
| `NEWS_NOT_MODELLED` | নিউজ ধরা হয়নি; লাইভ scanner-এর নিউজ সুরক্ষা এর কিছু setup আটকাত |
| `PRICES_NOT_EXNESS` | দাম ডেটা সরবরাহকারীর, Exness-এর নয় |
| `ASSUMED_EXNESS_STANDARD_CONTRACT` | Exness Standard-এর ধরে নেওয়া contract মান; আপনার নিশ্চিত করা মান নয় |
| `NOT_EXECUTABLE_RESEARCH_ONLY` | এখান থেকে কোনো ট্রেড নেওয়া যায় না |
| `SMALL_SAMPLE` | ১০০-এর কম বন্ধ ট্রেড: কোনো সিদ্ধান্ত নেওয়া যাবে না |
| `DEGRADED_INPUT_DATA` | DEGRADED ডেটায় চালানো |

## ঘ. রিপোর্ট

```
python -m ayesha.cli research runs
python -m ayesha.cli research report run_... --md report.md
```
রিপোর্টে আছে: R-এ ফল (খরচ বাদে), win rate-এর 95% পরিসীমা, drawdown, in/out-of-sample, walk-forward, session/দিক/H4 অনুযায়ী ভাগ,
$20–$5,000 কাল্পনিক equity-তে 0.01 লট সম্ভব কিনা, আর পুরো legacy `ayesha report` অংশ। টোকেন, pairing code বা আপনার নাম
রিপোর্টে থাকে না (redacted)। এখানে সব equity **কাল্পনিক**; আপনার আসল Exness equity research কখনো পড়ে না।

## ঙ. Parity (একই হিসাব কিনা যাচাই)

```
python -m ayesha.cli research parity --dataset ds_... --symbol EURUSD
```
জমানো dataset থেকে রান আর পুরনো CSV পথে রান একই ফল দেয় কিনা দেখে।
- `MATCHED`: হুবহু এক।
- `MATCHED_WITH_EXPLAINED_DIFFERENCES`: শুধু ব্যাখ্যা করা পার্থক্য, যেমন `SPREAD_ROUNDED_TO_WHOLE_POINTS` (CSV spread পূর্ণ point-এ গোল
  করে, OANDA-র সরাসরি ডেটা করে না)।
- `DIFFERENT`: আসল পার্থক্য, তালিকাসহ। আমাকে জানাবেন।

Parity শুধু হিসাবের মিল দেখায়; strategy লাভজনক কিনা সে সম্পর্কে কিছু বলে না।

## ঙ-২. Strategy Lab: তিনটি নিয়ম পাশাপাশি (1.0.0)

তিনটি research নিয়ম একই জমানো ডেটা, একই সময়-ভাগ, একই খরচ আর একই কাল্পনিক account-এ চালিয়ে পাশাপাশি দেখায়:
- **A `baseline-sweep-mss-fvg`**: আজকের লাইভ নিয়ম, একটুও না বদলে।
- **B `control-london-orb`**: খুব সাধারণ নিয়ম (London খোলার প্রথম এক ঘণ্টার range ভাঙলে)। A-র জটিলতা আসলে কিছু যোগ করে কিনা দেখার জন্য।
- **C `experimental-h1h4-trend`**: একমাত্র পরীক্ষামূলক নিয়ম (H4 trend, H1 EMA-তে ফিরে এসে আবার চলা)।

এগুলো **শুধু research**: B বা C কখনো ফোনে যায় না, READY হয় না, TradingView-এর Pine-এ নেই।

```
python -m ayesha.cli research strategies
python -m ayesha.cli research lab --dataset ds_... --symbols EURUSD,GBPUSD,USDJPY --holdout 2026-01-01
python -m ayesha.cli research report cmp_... --md lab.md
```
- `--holdout 2026-01-01`: ওই তারিখ থেকে শেষ পর্যন্ত ডেটা **সিল করা** থাকে; ফল দেখানো হয় না। সব সিদ্ধান্ত নেওয়ার পরে একবারই খুলবেন:
  একই কমান্ডে `--reveal-holdout` যোগ করে (audit trail-এ লেখা থাকে)। বারবার খুললে holdout-এর মূল্য থাকে না।
- `--quick`: খরচ আর parameter-এর অতিরিক্ত রান বাদ দেয় (দ্রুত, কম তথ্য)। পুরো রানে কয়েক মিনিট লাগতে পারে।
- একটা নিয়ম আলাদা চালাতে: `research run control-london-orb --dataset ds_... --symbols EURUSD`।

`lab.md`-এ আছে: প্রতিটি নিয়মের খরচ বাদে R, win rate ও expectancy-র 95% পরিসীমা, কত সংকেত বাতিল বা fill হয়নি, fold অনুযায়ী ফল,
spread +25%/+50%, slippage, এক bar দেরিতে ঢুকলে কী হয়, সেরা ৫% ট্রেড বাদ দিলে কী থাকে, $20 থেকে $5,000 কাল্পনিক account-এ
লাইভ risk নিয়মে (1% সীমা, minimum lot, দিনের ক্ষতির সীমা, একই currency-তে একটার বেশি নয়) কী হত, আর A-র তুলনায় পার্থক্য।
- **`NO_RANKING`**: কোনো নিয়মে ১০০-এর কম বন্ধ ট্রেড থাকলে ক্রম দেখানো হয় না। ক্রম দেখালেও সেটা শুধু এই ডেটার উপর
  (`IN_SAMPLE_ORDER_ONLY`), সুপারিশ নয়।
- **`NOT_DISTINGUISHABLE`**: পার্থক্য পরিসংখ্যানে আলাদা করা যায় না; "ভালো" ধরবেন না।
- **Benchmark parity `MATCHED`**: Lab-এর runner A-কে পুরনো replay-এর মতো হুবহু চালিয়েছে। `DIFFERENT` এলে ফলে ভরসা করবেন না,
  আমাকে জানাবেন (`lab` তখন exit 1 দেয়)।
- নিউজ এখানে **ধরা হয়নি** (ঐতিহাসিক calendar নেই); লাইভে নিউজ gate কিছু ট্রেড আটকাত।

একটা নিয়ম ভালো দেখালেও সেটা **যাচাই করা edge নয়**, আর কিছুই নিজে থেকে লাইভ হয় না।

## চ. Dashboard (শুধু এই PC-তে)

`desktop\windows\start-research.bat`-এ ডাবল-ক্লিক। ব্রাউজারে খুলবে: সারাংশ, ডেটা, রান (cumulative R চার্টসহ), লাইভ scanner-এর
অবস্থা (শুধু পড়া যায়; লট আর টাকার অঙ্ক লুকানো), স্ট্র্যাটেজি ল্যাব (তুলনা), ডায়াগনস্টিক, সেটিংস। রিপোর্ট সেখান থেকে ডাউনলোড করা যায়।
- এটা শুধু `127.0.0.1`-এ চলে; অন্য কম্পিউটার বা ফোন থেকে খোলা যায় না। প্রতিবার নতুন চাবি (key) থাকে লিংকে; লিংকটা কাউকে দেবেন না।
- Dashboard কিছু বদলাতে পারে না (কোনো বোতাম নেই যা কাজ চালায়)। রান বা ingest কমান্ড দিয়ে করুন।
- বন্ধ করতে window বন্ধ করুন।
- পরীক্ষা: `start-research.bat --check` (status, research doctor আর dashboard-এর নিরাপত্তা self-test; শেষে `Research checks passed.`)।

## ছ. সুস্থতা পরীক্ষা আর backup

```
python -m ayesha.cli research doctor
python -m ayesha.cli research backup
```
অথবা `desktop\windows\backup-research.bat`। Doctor দেখায়: config, isolation, registry, audit trail, worker, ফাইল, backup, disk।
শেষে `All research checks passed (warnings are advice).` আসা উচিত। Backup-এর সর্বশেষ ৭টা রাখা হয়; পুরনো research backup ছাড়া
আর কিছু মুছে ফেলা হয় না। ফেরত আনতে: `python -m ayesha.cli research restore <backup ফাইল>` তারপর `RESTORE` টাইপ করুন
(আগের অবস্থা `backups\pre-restore`-এ রাখা হয়)।

## জ. বন্ধ করা (rollback)

```
python -m ayesha.cli research disable
```
তারপর আগের মতো `start-ayesha.bat`। Research-এর ডেটা থেকে যায়; `ingest`, `run`, `parity` বন্ধ থাকে। আবার চালু: `research enable`।
Scanner কখনো research-এর উপর নির্ভর করে না। পুরো ধাপ: [RELEASE_ROLLBACK.md](RELEASE_ROLLBACK.md)।

## ঝ. সমস্যা হলে

| দেখা যাচ্ছে | মানে / কী করবেন |
|---|---|
| `Research is OFF` (exit 2) | `research enable` চালান |
| `BUSY` (exit 75) | আরেকটা research কাজ চলছে; শেষ হলে আবার চালান |
| `REFUSED` বা `REJECTED` (exit 2) | ইনপুট বা ডেটা গ্রহণযোগ্য নয়; বার্তায় কারণ লেখা থাকে (`inspect` দিয়ে দেখুন) |
| `OANDA rejected the token` | টোকেন ভুল বা বাতিল; `install.bat` আবার বা `python -m ayesha.cli set-token` |
| `TIMEOUT` / `RESOURCE_LIMIT` | কাজটা সময় বা মেমরির সীমা ছাড়িয়েছে; কম পেয়ার বা কম দিন দিয়ে চালান। Scanner-এর কোনো ক্ষতি হয় না |
| `CRASHED` | Worker হঠাৎ বন্ধ হয়েছে; অর্ধেক কাজ কখনো ব্যবহার হয় না। `research doctor` চালিয়ে ফল আমাকে পাঠান |
| `config invalid` | `research disable` চালান; ভুল ফাইল `config.invalid-<সময়>.yaml` নামে রেখে নতুন ঠিক ফাইল বানায় |

## ঞ. আমাকে কী পাঠাবেন

- `research report cmp_... --md lab.md`-এর `lab.md` (Strategy Lab), বা `research report run_... --md report.md`-এর `report.md`
  (আর চাইলে `research parity`-র আউটপুট)।
- সমস্যা হলে `research doctor`-এর আউটপুট।
- **পাঠাবেন না:** দামের ডেটা, `research.db`, টোকেন, pairing code, Exness-এর কোনো তথ্য।
