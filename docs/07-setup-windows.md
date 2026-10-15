# Windows PC-তে AYESHA চালানো (ধাপে ধাপে)

এই টুল শুধু বিশ্লেষণ করে। এটি কখনো Exness-এ অর্ডার দেয় না, পাসওয়ার্ড চায় না।

## ১. যা লাগবে
- Windows 10/11
- Python 3.12 (python.org থেকে; ইনস্টলের সময় "Add Python to PATH" টিক দিন)
- Exness-এর **MetaTrader 5** টার্মিনাল, নিজের অ্যাকাউন্টে লগইন করা (ডেমো হলেও চলবে)

## ২. ইনস্টল
PowerShell খুলে:

```powershell
cd C:\path\to\ayesha-fx\desktop
python -m pip install -e ".[dev,mt5]"
```

## ৩. আপনার অ্যাকাউন্টের আসল তথ্য দেখুন (সবচেয়ে গুরুত্বপূর্ণ ধাপ)
MT5 টার্মিনাল খোলা ও লগইন রেখে:

```powershell
ayesha spec-check
```

এটি দেখাবে: আপনার equity, প্রতিটি পেয়ারের broker symbol (যেমন `EURUSDm`), min lot, pip value, spread, এবং
**০.০১ লটে ১০/১৫/২০ পিপ SL হলে কত ডলার ও equity-র কত % ঝুঁকি।** কোনো সারিতে সেটা আপনার
risk budget (equity × 0.5%) এর বেশি হলে সেই ট্রেড নিরাপদ নয় — সিস্টেম `NO_TRADE` দেবে।

ফলাফল (লগইন নম্বর ছাড়া, ওটা আগেই লুকানো থাকে) আমাকে পাঠালে পরের ধাপ ঠিক করতে পারব।

MT5 ছাড়াই আন্দাজ দেখতে:

```powershell
ayesha lot-table --equity 20
ayesha lot-table --equity 20 --account-type StandardCent
```

## ৪. ইতিহাসের ডেটা নামানো
```powershell
mkdir data
ayesha export --symbol EURUSD --tf M15 --days 730 --out data\eurusd_m15.csv
```
অন্য পেয়ারের জন্য `--symbol` বদলান (GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY)।

## ৫. ব্যাকটেস্ট
```powershell
mkdir reports
ayesha backtest --csv data\eurusd_m15.csv --symbol EURUSD --equity 20 --split 2025-07-01 --out reports\eurusd.json --trades-csv reports\eurusd_trades.csv
```

- `--split` তারিখের আগের অংশ in-sample, পরের অংশ out-of-sample। **out-of-sample** ফলাফলটাই আসল।
- `expectancy_r` = গড়ে প্রতি ট্রেডে কত R (১R = পরিকল্পিত ক্ষতি)। শূন্যের নিচে মানে এই নিয়মে edge নেই।
- নিউজ ক্যালেন্ডার না দিলে রিপোর্টে সতর্কবার্তা থাকবে; লাইভে strict mode এমন ট্রেড আটকে দেবে।
- `reports\` ফোল্ডারের JSON ফাইল দুটো আমাকে পাঠান — আমি বিশ্লেষণ করব।

## ৬. একটা ট্রেড আইডিয়া যাচাই
```powershell
ayesha risk --equity 20 --symbol EURUSD --direction BUY --entry 1.0800 --stop 1.0785 --target 1.0840 --spread-pips 0.8 --news CLEAR
```
`"status": "NO_TRADE"` এলে `blockers` তালিকায় কারণ লেখা থাকবে।

## ৭. লাইভ স্ক্যানার (শুধু পরামর্শ, অর্ডার দেয় না)
```powershell
ayesha scan --news data\calendar.csv
```
- প্রতিটি M15 বার বন্ধ হলে সব পেয়ার স্ক্যান করে। READY সিগন্যাল এলে স্ক্রিনে দেখায়। ডেটাবেস থাকে `%USERPROFILE%\AyeshaFX\ayesha.db` এ।
- নিউজ ক্যালেন্ডার ছাড়া strict mode-এ সব সিগন্যাল `NO_TRADE: NEWS_UNVERIFIED` হবে। ক্যালেন্ডার CSV ফরম্যাট:
  `time_utc,currency,impact,title` (যেমন `2026-11-06T13:30:00Z,USD,HIGH,Non-Farm Payrolls`)। ফাইলে যে দিনগুলো আছে শুধু সেগুলোই "যাচাই করা" ধরা হয়।
- সিগন্যাল দেখতে: `ayesha signals`, বিস্তারিত: `ayesha signals --id <id>`
- নিজে ট্রেড নিলে জার্নালে লিখুন: `ayesha mark --id <id> --placed`, বন্ধ হলে `ayesha mark --id <id> --closed --pnl -0.10`।
  দিনে ২টা লস হলে সিস্টেম নতুন সিগন্যাল আটকে দেবে (`DAILY_RISK_PAUSE`)।

## ৮. ফোনে Telegram অ্যালার্ট (ঐচ্ছিক)
1. Telegram-এ @BotFather দিয়ে একটা bot বানান, token নিন। bot-কে একটা মেসেজ পাঠান, তারপর
   `https://api.telegram.org/bot<TOKEN>/getUpdates` খুলে `chat.id` নিন।
2. PowerShell-এ (token কখনো GitHub-এ রাখবেন না):
```powershell
setx AYESHA_TELEGRAM_BOT_TOKEN "<token>"
setx AYESHA_TELEGRAM_CHAT_ID "<chat id>"
```
3. নতুন PowerShell খুলে `ayesha telegram-test`, তারপর `ayesha scan --news data\calendar.csv --telegram`।
