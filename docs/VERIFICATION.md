# Verification checklist

Each item stays unchecked until it is seen working on the real platform. CI results are listed separately.

## Automated (every push)
- [x] No order-execution API anywhere (`scripts/check_no_order_api.py`)
- [x] Pine file matches the strategy spec (`scripts/generate_pine.py --check`)
- [x] Pine alert line carries every key the phone parser needs (`test_pine_alert_payload_matches_phone_parser`)
- [x] Python tests (Ubuntu + Windows)
- [x] Android core tests and APK build (`build-android.yml`)

## Owner, on TradingView (PC)
- [ ] Indicator compiles and adds to a 15m chart without errors
- [ ] ①–④ drawings appear on a past setup
- [ ] An "AYESHA → Any alert() function call" alert can be created on the current plan
- [ ] A real alert reaches the TradingView phone app

## Owner, on the phone
- [ ] APK installs; notification access granted
- [ ] "Test alert" shows an AYESHA notification marked CHART CANDIDATE / TEST
- [ ] A real TradingView alert is picked up and shows the same Entry/SL/TP as the chart
- [ ] "Open in TradingView" opens the right pair and timeframe

## Strategy
- [ ] Backtest on real historical data with spread and slippage (needs a data source)
- [ ] Forward paper period before any real-money use
