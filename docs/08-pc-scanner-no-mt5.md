# PC scanner, MT5 ছাড়া (OANDA ডেটা) → ফোনে AYESHA অ্যালার্ট

TradingView-এর ফ্রি (Basic) প্ল্যানে indicator-এর `alert()` চলে না (TradingView-এর pricing পাতায় Basic-এ শুধু price alert,
technical alert নেই; নিচে দেখুন)। তাই ফ্রি পথ হলো: **PC-তে AYESHA scanner → ntfy.sh relay → ফোনের AYESHA অ্যাপ**।
TradingView চার্ট আগের মতোই কারণ (①–④) দেখানোর জন্য থাকবে।

```
OANDA demo API (দাম, bid/ask) ─► PC scanner (নিয়ম + সব risk gate + নিউজ) ─► ntfy.sh (সই করা বার্তা) ─► AYESHA অ্যাপ
```

কেউ কোনো অর্ডার দেয় না। ট্রেড আপনি নিজে Exness অ্যাপে নেবেন।

## সবচেয়ে সহজ পথ: install.bat (একবার)
রেপো ডাউনলোড করে (GitHub → Code → Download ZIP, unzip) `desktop\windows\install.bat`-এ ডাবল-ক্লিক করুন। এটা ধাপে ধাপে:
১) Python আছে কিনা দেখে, ২) scanner ইনস্টল করে, ৩) OANDA টোকেন চায় (টাইপ করলে স্ক্রিনে দেখা যায় না, শুধু আপনার Windows-এ
থাকে), ৪) Exness equity চায়, ৫) Exness contract মান চায়, ৬) ফোনের pairing code দেখায়, ৭) `doctor` দিয়ে সব যাচাই করে,
শেষে জিজ্ঞেস করে Windows চালু হলে scanner নিজে চলবে কিনা (Y/N)। প্রতিদিন চালাতে `start-ayesha.bat`; বন্ধ হয়ে গেলে
৬০ সেকেন্ড পর নিজে আবার চালু হয়। equity বদলালে install.bat আবার চালান। কোনো সমস্যা হলে `python -m ayesha.cli doctor`
চালালে OK/FAIL তালিকা দেখাবে।

নিচের ধাপগুলো হাতে করার জন্য (install.bat যা করে, সেটাই)।

## যা লাগবে (একবারই)
1. **Python 3.12** (python.org থেকে, ইনস্টলের সময় "Add to PATH" টিক দিন)।
2. **OANDA fxTrade Practice (ডেমো) অ্যাকাউন্ট** — ফ্রি। শুধু দামের ডেটার জন্য; এতে টাকা লাগে না, ট্রেডও হবে না।
   লগইন করে **Manage API Access** থেকে একটা personal access token বানান।
   - এটা OANDA-র অফিসিয়াল API। কোনো scraping নয়। OANDA-র শর্ত (ব্যক্তিগত ব্যবহার, rate limit) মেনে চলে।
   - আপনার দেশে OANDA ডেমো খোলা না গেলে জানাবেন; তখন অন্য অনুমোদিত ডেটা উৎস বা MT5 (ঐচ্ছিক) লাগবে।
3. টোকেন Windows-এ একবার সেট করুন (Command Prompt):
   `setx AYESHA_OANDA_TOKEN "আপনার-টোকেন"` — টোকেন কখনো GitHub-এ বা কাউকে দেবেন না।
4. রেপো ডাউনলোড: GitHub → Code → Download ZIP (বা git clone), তারপর `desktop` ফোল্ডারে:
   `pip install -e .`

## Exness contract নিশ্চিত করা (একবার)
Exness অ্যাপ → EURUSD → **Specification** খুলুন। তারপর PC-তে:
`python -m ayesha.cli confirm-broker --account-type Standard`
অ্যাপে যা লেখা (contract size, min lot, step, max lot) হুবহু টাইপ করুন। না করলে প্রতিটা সিগন্যাল
`CONTRACT_SPEC_UNVERIFIED` থাকবে, কোনোটাই READY হবে না। মানগুলো শুধু আপনার PC-তে থাকে।

## ফোন জোড়া লাগানো (একবার)
1. PC-তে: `python -m ayesha.cli pair` → একটা কোড দেখাবে, যেমন `ABCD-EFGH-JKMN-PQRS`।
2. ফোনে AYESHA অ্যাপ → Settings → PC link-এ কোডটা লিখুন → "PC scanner থেকে সিগন্যাল নাও" টিক → Save।
3. PC-তে: `python -m ayesha.cli push-test` → অ্যাপের হোমে "PC test পাওয়া গেছে" দেখাবে।

## প্রতিদিন চালানো
`desktop\windows\start-ayesha.bat` খুলুন (equity install.bat-এ দেওয়া মান থেকে নেয়)। এটা চালায়:
`python -m ayesha.cli scan --feed oanda --equity 25 --account-type Standard --news-ff --push`
- Windows **Task Scheduler** → Create Basic Task → "When I log on" → এই .bat ফাইল: PC চালু হলেই scanner চলবে।
- PC বন্ধ বা ইন্টারনেট না থাকলে কোনো সিগন্যাল যাবে না। অ্যাপের হোমে ১২ মিনিটের বেশি খবর না এলে "PC অফলাইন" দেখাবে,
  scanner বন্ধ করলে "PC scanner বন্ধ" দেখাবে। ডেটা পুরনো হলে `DATA_STALE`, তখন কোনো READY হবে না।

## অ্যালার্টের মানে
| অবস্থা | মানে |
|---|---|
| **READY** | PC-র সব gate পাস: নিয়ম, RR ≥ ২, ডেটা তাজা, spread সীমার মধ্যে, নিউজ ফাঁকা, Exness spec মালিক-নিশ্চিত, লট বাজেটের মধ্যে। তবুও Exness অ্যাপে দাম/spread মিলিয়ে নিন। |
| **WATCH** | সেটআপ বৈধ কিন্তু এখনো entry নয় (যেমন M5 confirmation-এর অপেক্ষা)। নোটিফিকেশন হয় না; READY হলে একবার জানাবে। |
| **NO TRADE** | সেটআপ ছিল কিন্তু কোনো gate আটকেছে (কারণ লেখা থাকে, যেমন `MIN_LOT_EXCEEDS_RISK`)। নোটিফিকেশন হয় না, আর্কাইভে থাকে। |
| **UNVERIFIED** | সই ভুল, version আলাদা, দেরিতে আসা, watchlist-এর বাইরে ইত্যাদি। আর্কাইভে থাকে। |
| **CHART CANDIDATE** | শুধু TradingView চার্টের নিয়ম (যদি আপনার প্ল্যানে চার্ট alert চলে)। নিউজ/spread যাচাই হয়নি। |

**$20–30 Exness Standard USD:** 0.01 লট EURUSD-এ ১৮ pip SL-এ প্রায় $১.৯ ঝুঁকি = equity-র ৬–১০%। ০.৫–১% সীমায়
তাই প্রায় সব সিগন্যাল **NO TRADE (MIN_LOT_EXCEEDS_RISK)** হবে। এটা ভুল নয়, এটাই নিরাপদ উত্তর।

## যা বাইরের সার্ভিসে যায় (জেনে রাখুন)
- **ntfy.sh** (ফ্রি পাবলিক relay): সিগন্যালের লেখা (পেয়ার, লেভেল, অবস্থা) আর heartbeat। কোনো লগইন, ব্যালান্স, equity, টোকেন না।
  টপিকের নাম আপনার কোড থেকে তৈরি; কেউ নাম জানলে বার্তা পড়তে পারবে কিন্তু নকল পাঠাতে পারবে না (সই মিলবে না)।
- **OANDA**: শুধু দামের অনুরোধ (candles)। অর্ডার/ট্রেড endpoint কোডে নেই, CI তা পাহারা দেয়।
- **Forex Factory** ক্যালেন্ডার export: ঘণ্টায় সর্বোচ্চ একবার, ক্যাশ করে রাখে। না পেলে `NEWS_UNVERIFIED` (ট্রেড বন্ধ)।

## TradingView Basic সম্পর্কে
TradingView-এর pricing পাতা (https://www.tradingview.com/pricing/) অনুযায়ী Basic প্ল্যানে কয়েকটা price alert থাকে, কিন্তু
indicator-ভিত্তিক "technical alert" থাকে না; `Any alert() function call` একটা technical alert। তাই ফ্রি প্ল্যানে চার্ট থেকে ফোনে অ্যালার্ট
পাঠানোর পথ নির্ভরযোগ্য নয়। আপনার অ্যাকাউন্টে একবার চেষ্টা করে ফলাফল জানালে [VERIFICATION.md](VERIFICATION.md)-তে লিখে রাখব। প্ল্যান সীমা এড়ানোর কোনো চেষ্টা AYESHA করে না।
