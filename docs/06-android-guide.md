# AYESHA FX Android অ্যাপ (Android 13)

অ্যাপটা আপনার ফোনে TradingView অ্যাপের **AYESHA** নোটিফিকেশন পড়ে নিজের পরিষ্কার নোটিফিকেশন দেখায়।
সাথে থাকে বিস্তারিত তথ্য, আপনার equity অনুযায়ী লট হিসাব, আর এক চাপে TradingView-এ সেই পেয়ার খোলার বাটন।
এর জন্য কোনো সার্ভার, MT5 বা Exness লগইন লাগে না। অ্যাপ কখনো অর্ডার দেয় না।

```
PC: TradingView + AYESHA indicator + alert ("Notify in app")
        ↓
ফোন: TradingView অ্যাপ নোটিফিকেশন পায়
        ↓
AYESHA FX অ্যাপ সেটা পড়ে → নিজের নোটিফিকেশন + বিস্তারিত + লট
        ↓
"TradingView-এ খুলুন" → চার্টে ①–④ কারণ দেখুন → নিজে Exness অ্যাপে সিদ্ধান্ত নিন
```

## ইনস্টল
1. ফোনের ব্রাউজারে খুলুন: https://github.com/arnobai70-del/Aysha-Point/releases/latest/download/ayesha-fx.apk
2. ডাউনলোড হলে ফাইলটা খুলুন। "Unknown apps" অনুমতি চাইলে ব্রাউজারকে allow করুন, তারপর Install।
3. অ্যাপ খুলে **নোটিফিকেশন allow** করুন।
4. **অনুমতি দিন (Notification access)** চাপুন, তালিকায় AYESHA FX চালু করুন।
   - Android 13-এ "Restricted setting" লেখা এলে: Settings → Apps → AYESHA FX → উপরে ডানে ⋮ → **Allow restricted settings**,
     তারপর আবার Notification access চালু করুন।
5. **⚙️ Settings**-এ equity, risk %, account type (Standard / Cent) দিন।
6. **🧪 Test alert** চাপুন। একটা TEST নোটিফিকেশন এলে সব ঠিক আছে।

ফোনে TradingView অ্যাপ ইনস্টল আর লগইন থাকতে হবে, আর তার নোটিফিকেশনও চালু থাকতে হবে।

## আপডেট
নতুন ভার্সন এলে একই লিংক থেকে নামিয়ে ইনস্টল করুন। "App not installed / signature" error এলে পুরনো অ্যাপ uninstall করে
নতুনটা ইনস্টল করুন (কারণ: এখনো GitHub-এ নিজের signing key সেট করা হয়নি; নিচে দেখুন)।

## স্থায়ী signing key (ঐচ্ছিক, একবার)
GitHub repo → Settings → Secrets and variables → Actions-এ চারটা secret দিলে প্রতিটা APK একই key-তে সই হবে,
uninstall ছাড়াই আপডেট হবে: `AYESHA_KEYSTORE_BASE64`, `AYESHA_KEYSTORE_PASSWORD`, `AYESHA_KEY_ALIAS`, `AYESHA_KEY_PASSWORD`।
চাইলে বলবেন, keystore বানানোর ধাপ দিয়ে দেব।

## সীমাবদ্ধতা
- নোটিফিকেশন আসে TradingView-এর মাধ্যমে, তাই দেরি হতে পারে বা না-ও আসতে পারে। ফোন বা ইন্টারনেট বন্ধ থাকলে আসবে না।
- লট শুধু আন্দাজ (Exness-এর সাধারণ contract size ধরে)। EURJPY-র মতো cross পেয়ারে লট হিসাব হয় TradingView চার্টের USD রেট দিয়ে (নতুন indicator লাগবে)।
  রেট না পেলে বা পেয়ারটা চেনা না হলে (সোনা, index, crypto) অ্যাপ **RISK UNVERIFIED** দেখায়, কোনো লট দেখায় না, আর নোটিফিকেশনও দেয় না।
- Settings-এ ভুল সংখ্যা (০ বা মাইনাস equity, ১%-এর বেশি risk) সেভ হয় না।
- মেয়াদ গোনা হয় চার্টের সিগন্যাল বার থেকে। নোটিফিকেশন দেরিতে এলে অ্যাপ সেটা জানায়; মেয়াদ শেষ হয়ে এলে কোনো নোটিফিকেশন দেয় না।
- প্রতিটা সিগন্যাল **CHART CANDIDATE**: নিউজ, আসল spread আর Exness লট নিয়ম আপনাকে নিজে মিলিয়ে নিতে হবে।
- নিউজ ক্যালেন্ডার দেখা হয় না। বড় নিউজের আগে-পরে ট্রেড নেবেন না।

## PC link (ফ্রি পথ, ঐচ্ছিক)
PC-তে AYESHA scanner চালালে ([08-pc-scanner-no-mt5.md](08-pc-scanner-no-mt5.md)) সিগন্যাল সরাসরি এই অ্যাপে আসে, TradingView alert লাগে না।
Settings → PC link-এ PC-র `ayesha pair` কোড লিখে টিক দিন। তখন অ্যাপ ntfy.sh relay-এর সাথে একটা সংযোগ রাখে
(উপরে ছোট "AYESHA PC link" নোটিফিকেশন থাকবে)। এই কারণেই অ্যাপে এখন Internet অনুমতি আছে; শুধু এই কাজে লাগে, ফোন কিছু পাঠায় না।
কিছু ফোনে (Xiaomi, Oppo, Vivo, Samsung) battery saver অ্যাপ বন্ধ করে দেয়: Settings → Apps → AYESHA FX → Battery → **Unrestricted** দিন।

## অবস্থাগুলোর মানে
- **READY**: PC-র সব যাচাই পাস (সই, তাজা ডেটা, spread, নিউজ, Exness spec, লট)। শুধু এটাই পুরো যাচাই হওয়া সিগন্যাল।
- **চার্ট ক্যান্ডিডেট**: TradingView চার্টের নিয়ম; নিউজ/spread/Exness যাচাই হয়নি।
- **NO TRADE / UNVERIFIED / মেয়াদ শেষ**: নোটিফিকেশন হয় না, **আর্কাইভে** কারণসহ থাকে।
- হোমে **PC অফলাইন** দেখালে PC বন্ধ বা ইন্টারনেট নেই; তখন কোনো PC সিগন্যাল আসবে না।


## 0.4.0-এ নতুন
- **WATCH**: PC বলছে setup বৈধ কিন্তু এখনো entry নয় (যেমন M5 confirmation-এর অপেক্ষা)। সক্রিয় তালিকায় হলুদ, নোটিফিকেশন নেই।
  READY হলে একই সিগন্যাল আপডেট হয়ে একবার নোটিফিকেশন আসবে ("M5 নিশ্চিত")।
- সিগন্যালের পাতায় **Multi-timeframe** কার্ড: H4, H1, discount/premium, M15 setup, M5। ব্যাখ্যা: [09-mtf-and-backtest.md](09-mtf-and-backtest.md)।
- **📒 জার্নাল**: ট্রেড নিলে "✅ ট্রেড নিয়েছি", Exness-এ বন্ধ হলে আসল ফলাফল (USD) লিখুন। জার্নাল পাতায় মোট, জয়/হার,
  নিট ফল, drawdown, গড় R দেখাবে। শুধু আপনার লেখা আসল ফল; সিগন্যাল, টেস্ট বা ব্যাকটেস্ট এখানে গোনা হয় না।
- PC অফলাইন কিনা এখন PC-র নিজের সময় দিয়ে বিচার হয়, তাই পুরনো বার্তা দেরিতে এলেও ভুল করে "PC চলছে" দেখাবে না।
