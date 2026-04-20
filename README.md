# Bitget 漲幅榜反轉掃描器

這是依照你的需求重做的簡化版：
- 只用 Bitget 公開資料掃描
- 只抓漲幅榜前 10
- 只保留 24h 漲幅 > 30% 的標的
- 偵測高檔反轉
- 只送 Discord 通知
- 不自動下單
- 有簡單 Web UI 可看目前候選名單與反轉分數

## 反轉邏輯
目前採用「綜合評分」而不是單一指標：
1. 價格仍在近期高點附近
2. 5m RSI 先過熱，再跌回退出線
3. 5m 收盤跌回 EMA9 下方
4. 5m MACD histogram 轉弱
5. 5m 出現長上影轉弱 K
6. 15m 也開始轉弱
7. 5m 吞噬反轉型態

達到 `MIN_REVERSAL_SCORE` 就觸發 Discord。

## 啟動
```bash
pip install -r requirements.txt
cp .env.example .env
python app.py
```

部署平台若支援環境變數，直接填入 `.env.example` 內的值即可。

## 建議
- 若你想抓更兇的高檔轉弱，可以把 `MIN_REVERSAL_SCORE` 調到 5
- 若通知太少，可以降到 3
- 若只想掃現貨，把 `MARKET_TYPE=spot`
