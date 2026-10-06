# OpenD來源能力查核｜2026-10-06

只讀查核，SDK 10.11.7108、本機OpenD；未呼叫交易API。此為當時本機SDK／權限的結果，不宣稱所有OpenD版本永久不支援。

|項目|實際結果|雷達處置|
|---|---|---|
|VIX|搜尋回傳`US..VIX`；snapshot/history均回覆「暫不支援美股指數」|退役直接來源及Yahoo快照輪詢|
|10年期殖利率|搜尋回傳`BD.US10Y`；snapshot/history均拒絕該代碼格式|退役直接來源；TLT仍只稱ETF|
|美元指數|搜尋回傳`USDindex`；snapshot/history均拒絕該代碼格式|退役直接來源|
|直接原油|原油搜尋只有ETF／股票／板塊；`CLmain`搜尋空，未找到已驗證可用的直接来源；`US.WTI`是公司不是WTI油價|放棄未接通設計；保留USO ETF代理，不宣稱OpenD永遠無期貨能力|
|BTC/USD|`CC.BTCUSD`歷史分鐘線成功；來源epoch核對成功|獨立BTC來源，不混入ETF覆蓋率|
|選擇權異動|NVDA查詢ret=0，reported_all_count=24；僅檢視5筆樣本，有精確fill_time|候選按需查核，不宣稱取全／同窗口必有事件|

## 真實BTC適配器驗收

台北2026-10-06 23:36執行`collect_btc`：窗口終點美東11:36，最後完成分鐘11:35，status=ok，完整分鐘10/10、成交分鐘10/10、baseline_source=preceding_close。窗口變化+0.15709%，量31.526 BTC、量比0.7906。此僅為當次供應商幣對資料，非全球Bitcoin量；供應商延遲未獨立確認。

來源protobuf的timestamp先轉UTC aware時間，再由共用分析器轉美東；不從naive顯示時間猜時區。診斷不發布歷史報告、不污染正式報告slot。

另以美東2026-10-06 00:05終點實測跨午夜窗口：status=ok，完整／成交分鐘均10/10，前窗邊界有效，最後完成分鐘00:04。已檢查安裝SDK的decoder：依protobuf原順序跳過blank並逐列copy，與適配器的nonblank過濾順序一致。

## 報告原則

退役／未配置來源與固定取樣限制只在共同方法說明一次；不每10分鐘列成失敗。仍啟用的ETF／BTC本輪缺線、陳舊、權限或連線失敗仍披露，資料不足不稱市場平靜。既有報告及歷史證據保留。
