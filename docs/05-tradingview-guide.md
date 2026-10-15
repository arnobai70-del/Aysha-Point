# TradingView indicator আর ফোনে নোটিফিকেশন (MT5 লাগবে না)

ফাইল: [`tradingview/AyeshaSmartMoney.pine`](../tradingview/AyeshaSmartMoney.pine) (Pine v6, একটাই indicator)

এই সেটআপে PC-তে শুধু TradingView থাকবে। indicator নিজেই সেটআপ খুঁজবে, চার্টে কারণ এঁকে দেখাবে আর
ফোনে নোটিফিকেশন পাঠাবে। ট্রেড আপনি নিজে Exness অ্যাপে নেবেন।

## ১. চার্টে indicator বসানো (একবারই)
1. GitHub-এ `tradingview/AyeshaSmartMoney.pine` খুলে **Raw** চাপুন, সব কোড কপি করুন।
2. TradingView → চার্টের নিচে **Pine Editor** → পুরনো কোড মুছে পেস্ট করুন → **Save** → **Add to chart**।
3. চার্ট টাইমফ্রেম **15m** রাখুন।
4. indicator-এর ⚙️ Settings → **Account & alerts** অংশে আপনার equity (USD), risk % আর account type (Standard / StandardCent) দিন।
   এখান থেকেই লট হিসাব হবে।

## ২. ফোনে নোটিফিকেশন চালু
1. ফোনে **TradingView অ্যাপ** ইনস্টল করে একই অ্যাকাউন্টে লগইন করুন, নোটিফিকেশন allow করুন।
2. PC-তে একটা পেয়ার খুলুন (যেমন EURUSD, 15m) → উপরে **Alert (⏰)** → Condition: **AYESHA** → **Any alert() function call**।
3. Notifications ট্যাবে **Notify in app** টিক দিন → **Create**।
4. প্রতিটা পেয়ারের জন্য আলাদা alert লাগবে (EURUSD, GBPUSD, USDJPY...)।
   ফ্রি প্ল্যানে কয়টা alert রাখা যায় আর কতদিন চলে, সেটা TradingView-এর সীমা। আপনার প্ল্যানে যতটা allow করে, ততগুলো পেয়ার দিয়ে শুরু করুন (EURUSD আর GBPUSD দিয়ে শুরু করা ভালো)।

> **প্রথমে এটা পরীক্ষা করুন:** TradingView-এর ফ্রি (Basic) প্ল্যানে indicator-এর `alert()` দিয়ে alert বানানো যায় কিনা, সেটা এখনো নিশ্চিত না।
> একটা পেয়ারে উপরের মতো একটা alert বানানোর চেষ্টা করুন। "Create" হলে সব ঠিক। প্ল্যান আপগ্রেড চাইলে বা অপশনটা না থাকলে জানাবেন,
> তখন বিকল্প পথ (PC-তে AYESHA scanner চালিয়ে ফোনে push) লাগবে। দেখুন [DECISIONS.md](DECISIONS.md)।
>
> **indicator আপডেট করলে:** নতুন কোড Save করার পর পুরনো AYESHA alert মুছে আবার নতুন করে বানান। পুরনো alert পুরনো কোডেই চলে।

## ৩. নোটিফিকেশন এলে কী দেখবেন
প্রতিটা নোটিফিকেশন একটা **CHART CANDIDATE** (চার্ট ক্যান্ডিডেট): চার্টের নিয়মে সেটআপ পাওয়া গেছে, কিন্তু নিউজ, Exness-এর আসল spread
আর Exness-এর লট নিয়ম যাচাই হয়নি। এই তিনটা আপনি নিজে দেখে তবেই ট্রেড বিবেচনা করবেন।

নোটিফিকেশনে থাকবে: BUY/SELL, পেয়ার, কেন (১-২-৩), Entry, SL, TP, RR, আনুমানিক লট আর সর্বোচ্চ লস।
সেই পেয়ার TradingView-এ খুললে চার্টে এই ধাপগুলো আঁকা থাকবে:

| চিহ্ন | মানে |
|---|---|
| ① হলুদ লেবেল | কোন liquidity (PDH/PDL, Asia high/low, swing, EQH/EQL) sweep হয়েছে |
| ② সবুজ/লাল লেবেল | উল্টো দিকে MSS (displacement সহ structure break) |
| ③ নীল বক্স | FVG, এখানেই entry zone |
| ④ লাইন + লেবেল | Entry (মোটা নীল), SL (লাল), TP (টিল), RR, লট |

শেষের ৫টা সেটআপ চার্টে থেকে যায়। মেয়াদ শেষ হলে (৮ বার) সেগুলো ধূসর হয়ে যায়।
ডান-উপরের টেবিলে সেশন, HTF bias, সেটআপ অবস্থা আর `VERSION #hash` দেখা যাবে।

## সীমাবদ্ধতা (মনে রাখবেন)
- লট শুধু **আন্দাজ**: আপনার দেওয়া equity আর Exness-এর সাধারণ contract size (Standard ১ লট = ১০০,০০০, Cent ১ লট = ১,০০০) দিয়ে হিসাব।
  Exness অ্যাপে অর্ডার দেওয়ার আগে মিলিয়ে নিন।
- Spread আন্দাজ (settings-এ `Assumed spread`)। Exness-এ আসল spread বেশি হলে ট্রেড নেবেন না।
- নিউজ ক্যালেন্ডার Pine পড়তে পারে না। বড় নিউজের (NFP, CPI, সুদের হার) ৩০ মিনিট আগে-পরে ট্রেড নেবেন না।
- `0.01 lot risks $… > budget` লেখা এলে মানে লট আপনার risk-এর চেয়ে বড়, তাই **NO TRADE**। ডিফল্টে এমন সেটআপের নোটিফিকেশন আসে না।
- TradingView-এর দাম (যেমন OANDA/FX feed) আর Exness-এর দাম এক-দুই পিপ আলাদা হতে পারে।
- indicator কখনো অর্ডার দেয় না।
- প্রথমবার Add to chart করলে কোনো লাল error দেখালে স্ক্রিনশট পাঠান।
