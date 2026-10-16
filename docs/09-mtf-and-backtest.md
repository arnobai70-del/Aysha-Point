# Multi-timeframe বিশ্লেষণ আর ব্যাকটেস্ট রিপোর্ট

## একটা setup, অনেক timeframe
AYESHA প্রতিটা timeframe-এর জন্য আলাদা সিগন্যাল পাঠায় না। সব মিলিয়ে **একটাই** setup, আর তার সাথে ব্যাখ্যা:

| Timeframe | কাজ | ফোনে যা দেখবেন |
|---|---|---|
| **H4** | বড় ছবি (context): ঊর্ধ্বমুখী, নিম্নমুখী না সাইডওয়ে | `✅ H4 (বড় ছবি): ঊর্ধ্বমুখী` |
| **H1** | bias, শেষ BOS/CHoCH, entry H1 রেঞ্জের discount না premium অর্ধেকে | `✅ H1 bias ... · শেষ ব্রেক BOS UP`, `✅ discount` |
| **M15** | আসল setup: liquidity sweep → MSS → FVG | `✅ M15 setup: PDL sweep → CHOCH → FVG` |
| **M5** | ঐচ্ছিক confirmation (ডিফল্ট বন্ধ) | `➖ M5 confirmation: বন্ধ` |
| **M1** | scalp: **বন্ধ**। আলাদা যাচাই ছাড়া চালু করা যায় না (কোড নিজেই আটকায়) | |

- H1 আর H4 **দুটোই** setup-এর উল্টো দিকে হলে setup বাতিল (`HTF_CONTEXT_AGAINST`)।
- ✅ = ট্রেডের দিকে, ⚠️ = উল্টো, ➖ = নিরপেক্ষ বা অজানা। এগুলো চার্টের নিয়মভিত্তিক মডেল, ব্যাংকের অর্ডার দেখা নয়।

### M5 confirmation চালু করলে কী বদলায়
`contracts/strategy-spec.yaml`-এ `mtf.confirm_timeframe: M5` দিলে:
1. M15 setup হলে ফোনে **WATCH** (নোটিফিকেশন নেই): "M5 confirmation-এর অপেক্ষা"।
2. দাম entry zone-এ এলে, ৬টা M5 candle-এর মধ্যে একটা শক্ত M5 candle (body ≥ 0.8 × ATR) ট্রেডের দিকে বন্ধ হতে হবে।
3. হলে: entry = সেই candle-এর close (market), RR আবার হিসাব হয়, সব gate আবার চলে, তারপর **READY** নোটিফিকেশন।
   এই entry মাত্র ১৫ মিনিট বৈধ।
4. না হলে (stop আগে, target আগে, সময় শেষ, বা RR কমে গেলে): NO TRADE, কারণসহ আর্কাইভে।

এটা এখনো আসল ডেটায় যাচাই হয়নি, তাই ডিফল্ট বন্ধ। নিচের রিপোর্টে "m15" আর "m5confirm" পাশাপাশি তুলনা দেখা যাবে।

### TradingView চার্ট বনাম PC
চার্টের টেবিলে **H4 CONTEXT** আর **FEED NOTE** সারি আছে। TradingView-এর feed (যেমন FX বা FOREXCOM) PC-র OANDA feed আর
Exness-এর দাম থেকে সামান্য আলাদা হতে পারে, তাই চার্ট আর PC সবসময় হুবহু মিলবে এমন নয়। চার্টে OANDA:EURUSD খুললে PC-র
সাথে একই feed দেখবেন। Exness-এর দাম তবুও আলাদা হতে পারে।

## ব্যাকটেস্ট রিপোর্ট (আসল ডেটায়)
Claude-এর কাজের পরিবেশ থেকে OANDA-তে যাওয়া যায় না, আর আপনার টোকেন ছাড়া আসল ডেটা পাওয়া যায় না। তাই রিপোর্ট
GitHub-এ চলে, আপনার টোকেন GitHub-এর গোপন "secret" হিসেবে থাকে (রেপোতে কখনো লেখা হয় না)।

1. GitHub রেপো → **Settings → Secrets and variables → Actions → New repository secret**।
   Name: `AYESHA_OANDA_TOKEN`, Value: আপনার OANDA practice টোকেন → Add secret।
2. রেপো → **Actions → backtest → Run workflow** (ডিফল্ট: ৩ বছর, ৬টা পেয়ার) → Run।
3. শেষ হলে সেই run-এর পাতায় রিপোর্ট দেখা যাবে, আর **backtest-report** artifact-এ JSON + Markdown।
   দামের ডেটা কোথাও commit হয় না।

PC থেকেও চালানো যায়:
```
python -m ayesha.cli export --feed oanda --symbol EURUSD --tf M15 --days 1095 --out data\EURUSD_M15.csv
python -m ayesha.cli export --feed oanda --symbol EURUSD --tf M5  --days 1095 --out data\EURUSD_M5.csv
python -m ayesha.cli report --data-dir data --pairs EURUSD --split 2025-01-01 --label "OANDA practice" --md report.md
```

### রিপোর্টে যা থাকে
- মোট সিগন্যাল, বন্ধ ট্রেড, জয়/হার, win rate (৯৫% সীমাসহ), গড় জয়/হার (R), পরিকল্পিত net RR,
  খরচের পরে expectancy (R), profit factor, সর্বোচ্চ drawdown, টানা হারের সংখ্যা।
- In-sample বনাম out-of-sample (split তারিখের আগে/পরে)।
- Walk-forward: একই নিয়ম (কোনো optimisation ছাড়া) পরপর ৪টা সময়ভাগে। কতগুলো ভাগে expectancy ধনাত্মক।
- পেয়ার, সেশন, দিক, H4 context আর mode (m15 / m5confirm) অনুযায়ী ভাগ।
- **$20, $25, $30, $100, $500, $1,000, $5,000 Exness Standard**, ০.৫% আর ১% ঝুঁকিতে: 0.01 লটে কতগুলো ট্রেড নেওয়া যেত,
  আর নিলে USD ফল কত। সাথে একটা কাল্পনিক অ্যাকাউন্ট: প্রতিটা ট্রেডের লট আগের ফলের পরের equity থেকে, দৈনিক ২%, দিনে ২ লস,
  খোলা ঝুঁকি ১% আর ১% hard cap মেনে। এগুলো আয়ের পূর্বাভাস নয়।
- `--news calendar.csv` দিলে একই ক্যান্ডেলে তিনটা তুলনা: নিউজ ছাড়া, পুরনো ৩০/৩০, নতুন নিউজ সুরক্ষা
  ([11-news-and-capital-guide.md](11-news-and-capital-guide.md) অংশ ছ)।

### রিপোর্ট কীভাবে পড়বেন
- ১০০-র কম বন্ধ ট্রেড হলে রিপোর্ট নিজেই "too small to conclude" লেখে। তখন কোনো সিদ্ধান্ত নয়।
- শুধু win rate দেখবেন না। খরচের পরে expectancy আর out-of-sample ফলই আসল। win rate বাড়াতে নিয়ম বদলানো হয় না।
- নিউজ ক্যালেন্ডারের পুরনো ডেটা না দিলে রিপোর্টে "NOT RUN (BLOCKED BY DATA)" লেখা থাকে; লাইভে নিউজের কারণে আরও setup বাদ যাবে।
  নিউজের দিক (actual বনাম forecast) কখনো ব্যাকটেস্ট হয় না: "NEWS DIRECTION NOT BACKTESTED"।
- এটা অতীতের হিসাব, ভবিষ্যতের লাভের প্রতিশ্রুতি নয়।
