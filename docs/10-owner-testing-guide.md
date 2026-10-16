# নিজের PC, TradingView Basic আর Android 13 ফোনে পরীক্ষার নির্দেশিকা

এই পরীক্ষাগুলো শুধু **ডেমো / কাগজে-কলমে**। আসল টাকায় ট্রেড নয়। AYESHA কখনো অর্ডার দেয় না।
প্রতিটা ধাপের শেষে "যা দেখা উচিত" লেখা আছে। যা দেখলেন (বা ভুল কিছু) তা স্ক্রিনশটসহ জানাবেন, আমি
[VERIFICATION.md](VERIFICATION.md)-তে প্রমাণ হিসেবে লিখে রাখব। আসল ডেটা, ফোনে পরীক্ষা আর অন্তত ৩০ দিনের ডেমো
ফরোয়ার্ড টেস্ট ছাড়া "সিগন্যাল লাভজনক" বা "লাইভ সংযোগ সফল" বলা যাবে না।
নিউজ সুরক্ষা আর capital (equity) আপডেটের পুরো ব্যাখ্যা: [11-news-and-capital-guide.md](11-news-and-capital-guide.md)।

---

## ক. Windows PC

### ক১. ইনস্টল (একবার, ~১০ মিনিট)
1. Python 3.12 ইনস্টল করুন: https://www.python.org/downloads/ → ইনস্টলের প্রথম পাতায় **"Add python.exe to PATH"** টিক।
2. OANDA ডেমো অ্যাকাউন্ট: https://www.oanda.com → fxTrade **Practice** খুলুন → লগইন → **Manage API Access** → Generate।
   টোকেনটা কপি করে রাখুন (কাউকে দেবেন না, কোথাও পোস্ট করবেন না)।
3. GitHub রেপো → **Code → Download ZIP** → unzip করুন (যেমন `C:\AYESHA`)।
4. `desktop\windows\install.bat`-এ ডাবল-ক্লিক। প্রশ্নগুলো:
   - **1/5 Token (hidden)**: টোকেন paste করে Enter (টাইপ করা অক্ষর দেখা যাবে না, এটাই ঠিক)।
   - **2/5 Capital**: Exness অ্যাপ → Accounts-এ যে **equity** দেখায়, USD-তে, যেমন `25`; তারপর খোলা ট্রেড (না থাকলে Enter)।
   - **3/5 Exness contract per pair**: প্রথমে account leverage (যেমন `2000`, unlimited হলে `U`)। তারপর প্রতিটা পেয়ার
     (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY): Exness অ্যাপ → পেয়ার → ⓘ Specification থেকে contract size, min lot,
     step, max lot হুবহু, আর শান্ত বাজারে সাধারণ spread (pip)। পরের পেয়ারে মান একই হলে `Y` (শুধু অ্যাপে দেখে নিয়ে), আলাদা হলে
     `N`, বাদ দিতে `S` (সেই পেয়ারে READY হবে না)।
   - **4/5 Pairing code**: লিখে রাখুন (ফোনে লাগবে)।
   - **Start automatically?**: চাইলে `Y`।

**যা দেখা উচিত:** শেষে health check-এ `OK  OANDA token`, `OK  OANDA prices` (বাজার বন্ধ থাকলে quote age বেশি দেখাবে),
`OK  Exness contract` (leverage সহ), `OK  Capital` (কত ঘণ্টা আগে নিশ্চিত, সংখ্যা দেখায় না), `OK  Pairing code`,
`OK  News calendar`। কোনো `FAIL` থাকলে লেখাটা পাঠান।

### ক২. প্রতিদিন চালানো
`desktop\windows\start-ayesha.bat` ডাবল-ক্লিক। প্রথমে **Capital check for this session** জিজ্ঞেস করবে: Exness অ্যাপে equity
দেখে লিখুন (একই থাকলে Enter), তারপর খোলা ট্রেড। এই নিশ্চয়তা ২৪ ঘণ্টা বৈধ (ডিপোজিট/উইথড্রর পরে ৪ ঘণ্টা)।
**যা দেখা উচিত:** `Connected read-only ... OANDA data feed` আর প্রতি ১৫ মিনিটে নতুন বার প্রসেস।
- ইন্টারনেট বন্ধ করলে: `FEED UNREACHABLE ... will retry`, তারপর ৬০ সেকেন্ড পর নিজে আবার চেষ্টা করবে। ইন্টারনেট ফিরলে চলবে।
- টোকেন ভুল বা বাতিল হলে: `OANDA REJECTED THE TOKEN` লিখে থেমে যাবে (বারবার চেষ্টা করবে না)। নতুন টোকেন নিয়ে install.bat আবার চালান।
- বন্ধ করতে: জানালাটা বন্ধ করুন। ফোনে "PC scanner বন্ধ" বা কিছুক্ষণ পরে "PC অফলাইন" দেখাবে।

### ক৩. আসল ডেটায় ব্যাকটেস্ট, টোকেন GitHub-এ না রেখে
`desktop\windows\backtest-local.bat` ডাবল-ক্লিক (৩ বছর, ৬টা পেয়ার; ১০–৩০ মিনিট লাগতে পারে)।
শুধু কয়েকটা পেয়ার: Command Prompt-এ `backtest-local.bat --pairs EURUSD,GBPUSD --days 730`।
**যা দেখা উচিত:** শেষে `Report: C:\Users\<আপনি>\AyeshaFX\backtest\<তারিখ>\backtest-report.md` আর ফোল্ডারটা খুলে যাবে।
`backtest-report.md` আর `.json` ফাইল দুটো আমাকে পাঠান। দামের ডেটা (`data` ফোল্ডার) পাঠানোর দরকার নেই।
কীভাবে পড়বেন: [09-mtf-and-backtest.md](09-mtf-and-backtest.md)।

### ক৪. টোকেন মুছে ফেলা
`python -m ayesha.cli set-token --remove` (desktop ফোল্ডারে), আর OANDA সাইটে টোকেনটা Revoke করুন।

---

## খ. TradingView Basic

1. TradingView → চার্ট খুলুন → **OANDA:EURUSD**, timeframe **15m** (PC-র সাথে একই feed)।
2. নিচে **Pine Editor** → সব মুছে `tradingview/AyeshaSmartMoney.pine`-এর পুরো লেখা paste → **Add to chart**।
   **যা দেখা উচিত:** কোনো লাল error নেই; ডান-উপরে টেবিলে PAIR, SESSION, H1 BIAS, SETUP, RISK, VERSION
   (`0.4.0 #9bb5e8ed5937`), TV FEED, TIMEFRAME `15m OK`, H4 CONTEXT, FEED NOTE `same feed as PC (OANDA)`।
   পুরনো version-এর indicator থাকলে সরিয়ে নতুনটা দিন; ফোনের অ্যাপ আর Pine একই version না হলে চার্টের সিগন্যাল UNVERIFIED হবে।
   error এলে লাইনের নম্বরসহ স্ক্রিনশট পাঠান।
3. চার্ট পিছনে টেনে ①–④ চিহ্ন (sweep, MSS, FVG, Entry/SL/TP) খুঁজুন; একটার স্ক্রিনশট পাঠান।
4. Basic-এ alert পরীক্ষা: ⏰ Alert → Condition: **AYESHA → Any alert() function call** → Create।
   **জানান:** তৈরি হলো, নাকি upgrade চাইল। (Basic-এ technical alert না থাকাই প্রত্যাশিত; তখন PC scanner-ই ফোনে সিগন্যাল পাঠাবে।)
5. 5m বা 1h চার্টে বদলালে TIMEFRAME সারি লাল হয়ে "Use 15m (alerts off)" দেখাবে, এটা ঠিক আচরণ।

---

## গ. Android 13 ফোন

### গ১. ইনস্টল
1. পুরনো AYESHA থাকলে আগে **জার্নাল ব্যাকআপ** নিন (নিচে গ৪), তারপর uninstall।
2. ফোনের ব্রাউজারে সর্বশেষ রিলিজ থেকে `ayesha-fx.apk` নামান → খুলুন → "Install unknown apps" অনুমতি → Install।
3. অ্যাপ খুলুন → নোটিফিকেশন অনুমতি **Allow**।
4. "অনুমতি দিন (Notification access)" → AYESHA FX চালু। "Restricted setting" দেখালে: Settings → Apps → AYESHA FX → ⋮ → Allow restricted settings, তারপর আবার।
5. ⚙️ Settings → Exness equity লিখে **✅ Update capital** (PC-তে যা লিখেছেন সেই একই সংখ্যা), risk (০.৫), Exness Standard;
   PC link-এ pairing code লিখুন, "PC scanner থেকে সিগন্যাল নাও" টিক → Save।
   **যা দেখা উচিত:** হোমের 💰 Capital কার্ডে "শেষ নিশ্চিত: এইমাত্র"; PC থেকে সিগন্যাল এলে "✅ শেষ PC সিগন্যালের equity-র সাথে মিল আছে"।

### গ২. সংযোগ পরীক্ষা
1. PC-তে (desktop ফোল্ডারে) `python -m ayesha.cli push-test`।
   **যা দেখা উচিত:** ফোনের হোমে "✅ PC test পাওয়া গেছে (এইমাত্র)"।
2. PC-তে start-ayesha.bat চালু রাখুন → কয়েক মিনিটে "✅ PC চলছে, ডেটা ঠিক আছে"।
3. scanner বন্ধ করুন → "⏹ PC scanner বন্ধ করা হয়েছে"। PC-র ইন্টারনেট বন্ধ করে ১২ মিনিট পর → "⚠️ PC অফলাইন"।
4. ফোন ১০ মিনিট airplane mode-এ রাখুন, তারপর চালু করুন → সংযোগ নিজে ফিরবে, কোনো সিগন্যাল দুবার আসবে না।
5. 🧪 Test চাপুন → "চার্ট ক্যান্ডিডেট · TEST" নোটিফিকেশন; চাপলে বিস্তারিত পাতা খুলবে।

### গ৩. সিগন্যাল এলে
- **READY** নোটিফিকেশন চাপুন → বিস্তারিত পাতায় Entry/SL/TP/RR, লট, Multi-timeframe কার্ড, কারণ।
- "TradingView-এ খুলুন" → একই পেয়ার ১৫m চার্টে খোলা উচিত। লেভেল চার্টের ①–④-এর সাথে মিলছে কিনা স্ক্রিনশট পাঠান
  (feed আলাদা হলে সামান্য পার্থক্য স্বাভাবিক)।
- $20–30 equity-তে প্রায় সব সিগন্যাল **NO TRADE (MIN_LOT_EXCEEDS_RISK)** হবে, আর্কাইভে কারণসহ থাকবে। এটাই নিরাপদ উত্তর।
  equity বাড়লে (ডিপোজিট বা লাভ) Update capital করুন; একই নিয়মে লট নিজে থেকে হিসাব হবে, ঝুঁকি % বাড়বে না।
- নিউজের সময় 📰/⛔/📊 নোটিফিকেশন আসবে; এগুলো ট্রেড সিগন্যাল নয়। লকআউটের সময় কোনো READY আসবে না।
- ডেমো ফরোয়ার্ড টেস্ট: প্রতিটা READY-এ (ডেমো অ্যাকাউন্টে বা শুধু কাগজে) "✅ ট্রেড নিয়েছি", শেষে আসল ফলাফল লিখুন।
  ৩০ দিন পরে 📒 জার্নালের স্ক্রিনশট আর ব্যাকআপ ফাইল পাঠান।

### গ৪. Android আপডেট, জার্নাল না হারিয়ে
Android শুধু তখনই ডেটা রেখে আপডেট করে, যখন নতুন APK **একই signing key**-তে সই করা। এখনকার রিলিজগুলো CI-এর অস্থায়ী
key-তে সই করা, তাই প্রতি আপডেটে uninstall লাগে। দুটো ব্যবস্থা:

**১) ব্যাকআপ (সবসময় করুন):** 📒 জার্নাল → **💾 ব্যাকআপ ফাইল** → Downloads বা Google Drive-এ সেভ। uninstall + নতুন install-এর পরে
📒 জার্নাল → **📂 ফেরত আনুন** → সেই ফাইল। সিগন্যাল, জার্নাল আর settings ফিরে আসবে (pairing code আবার লিখতে হবে)।
একই ফাইল দুবার ফেরত আনলেও কিছু দুবার হয় না; লেখা ফলাফল কখনো মুছে যায় না।

**২) স্থায়ী signing key (একবার, তারপর আর uninstall লাগবে না):**
1. PC-তে `desktop\windows\make-signing-key.bat` চালান। ফোল্ডার খুলবে: `ayesha-release.p12` আর `github-secrets-DELETE-AFTER-USE.txt`।
2. GitHub রেপো → Settings → Secrets and variables → Actions → **New repository secret**, ফাইলে লেখা চারটা:
   `AYESHA_KEYSTORE_BASE64`, `AYESHA_KEYSTORE_PASSWORD`, `AYESHA_KEY_ALIAS`, `AYESHA_KEY_PASSWORD`।
3. `ayesha-release.p12` আর পাসওয়ার্ড একটা USB বা নিরাপদ জায়গায় কপি করুন, তারপর txt ফাইলটা মুছে দিন। এটা হারালে
   পরের আপডেটে আবার uninstall লাগবে। কখনো GitHub-এ বা কাউকে দেবেন না।
4. আমাকে জানালে নতুন build চালাব। রিলিজ নোটে "owner release key" আর **Signer certificate SHA-256** দেখাবে।
   প্রথমবার এই key-র APK-তে যেতে একবার ব্যাকআপ → uninstall → install → ফেরত আনা লাগবে; এরপর থেকে সরাসরি আপডেট।
   প্রতিটা রিলিজে SHA-256 একই থাকা উচিত।

---

## যা পাঠাবেন (চেকলিস্ট)
- [ ] install.bat-এর health check (OK/FAIL) লেখা
- [ ] backtest-report.md + .json
- [ ] TradingView: indicator compile হলো কিনা, টেবিল আর ①–④-এর স্ক্রিনশট, Basic alert-এর ফল
- [ ] ফোন: "PC test পাওয়া গেছে", "PC চলছে", "PC অফলাইন/বন্ধ"-এর স্ক্রিনশট
- [ ] প্রথম READY বা NO TRADE সিগন্যালের বিস্তারিত পাতা আর TradingView চার্টের স্ক্রিনশট
- [ ] ৩০ দিন পর জার্নালের স্ক্রিনশট আর ব্যাকআপ ফাইল
- [ ] `python -m ayesha.cli capital --history`-এর লেখা (সংখ্যা ঢেকে দিতে পারেন) আর একটা নিউজ নোটিফিকেশনের স্ক্রিনশট
