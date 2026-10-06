# US Market Hotspot Radar

只讀的美股 10 分鐘異常雷達。先觀察市場價格與成交量，再聚類；僅對通過異常篩選的候選事件調查催化劑。不是新聞摘要、價格預測、推薦或交易系統。

## 執行時間

- 每個實際美股交易日，固定 **Asia/Taipei 21:20** 起，每 10 分鐘一次。
- 結束時間依 XNYS 交易日曆的當日正常盤收盤；最後一輪包含收盤時點。
- 夏令時間：一般交易日台北 21:20 至次日 04:00。
- 冬令時間：一般交易日台北 21:20 至次日 05:00。
- 起點不隨夏令時間改變，因此夏令時間從美東 09:20、冬令時間從 08:20 開始，**包含盤前**。
- 美國休市日及週末跳過；提早收盤日依實際收盤提前停止。
- 排程採台北 `*/10 0-5,21-23 * * *` 外框；Python 交易日曆 gate 在 21:20 前、收盤後及非交易日不查行情、不喚醒模型。不要把外框的每次 tick 當作執行了市場掃描。

## 報告歸檔

- 美東交易日命名：`reports/YYYY-MM-DD.md`。
- 同一天每輪報告追加到同一份 Markdown，不覆蓋之前內容；跨台北午夜仍歸屬同一美東交易日。
- 每轮完成後 commit / push，查回 GitHub 原檔案以驗證發布。
- `slot` 去重，重試不得重複追加；GitHub 失敗保留本機未推送內容。
- 首次正式報告從啟用後第一個合資格時點產生；不捏造過去漏掉的輪次。
- GitHub repo 為私有；正常輪次不向 Telegram 重複發送，排程引擎失敗通知送回使用者。

## 方法與限制

- 四大指數 ETF：SPY、QQQ、IWM、DIA。
- 11 板塊 ETF：XLK、XLF、XLE、XLV、XLY、XLP、XLI、XLB、XLU、XLRE、XLC。
- 主題／跨資產代理：SOXX、SMH、IGV、XBI、IBB、KRE、XOP、OIH、ITA、ARKK、IBIT、GLD、TLT；USO 為原油 ETF 代理，不是現貨原油。
- 優先使用本機 Futu OpenD 的同時間窗口完整一分鐘 K 線。計算 10 分鐘變化、上一窗口變化及加速度、相對 SPY/QQQ、成交量相對前 30 分鐘基準，以及區間波動。不得拿全天漲跌或全天量冒充 10 分鐘異常。
- 對候選聚類再查代表成分股。樣本廣度不是完整成分股廣度；缺資料、零成交和陳舊資料不是市場平靜的證據。
- USO 保留 Futu 一分鐘 K 線分析並獨立作為原油 ETF 代理聚類（不當作能源股成分廣度）；不再設計直接原油現貨／期貨掃描。
- BTC/USD 現貨幣對已接入 Futu `CC.BTCUSD` 同窗口一分鐘線；保留來源protobuf的unix epoch轉成aware時間，完成10分鐘且成交／時效／前窗邊界合格才納入。快照`btc`與29檔ETF覆蓋率分開、量單位為BTC，不代表全球Bitcoin成交量；|10分鐘變化|≥0.6%觸發跨資產注意訊號。
- 分數是保守的啟發式注意力排序，不是報酬预测。方法与实际筛选条件以 `radar.py` 为准；资料不足须降分或不列入。
- 通過價格異常篩選後，Hermes 才查前 30–60 分鐘可靠媒體／公司／官方資料；僅同時發生不是因果。催化劑未確認時寫 `Unconfirmed`。
- 無可信熱點不硬湊 Top 3；輸出「最近 10 分鐘沒有發現具有足夠可信度的市場熱點。」並披露重大資料缺口。資料源失敗須標示「資料不足／掃描受阻」，不等同無異常。
- VIX／10年期殖利率／美元指數已退出生產雷達，停止Yahoo快照抽樣及`quotes.sqlite`基準更新；歷史快照與舊報告保留。OpenD能搜尋出標的並不代表行情接口支援。來源實測見 `validation/source-scope-2026-10-06.md`。
- 選擇權異動接口可用，但只是已確認候選的按需研究；不做全市場每10分鐘普查，不每輪列固定缺口。TLT/GLD/IBIT仍是ETF代理；沒有有效資料的本輪ETF或BTC失效才列警示，固定範圍與取樣限制只放共同方法文件。
- 沒有候選的輪次由程式直接產生／發布簡短報告；資料不足時發布明確的受阻報告，絕不稱市場平靜。只有確認候選或明顯跨市場異動才啟動研究 Agent，避免無內容的模型呼叫。

## 執行依賴

需在本機運行 Hermes gateway／排程器、Futu OpenD（行情已登入及足夠權限）、Python 虛擬環境，以及已登入的 GitHub CLI／git。**GitHub 僅儲存報告，不在 GitHub Actions 上查本機行情。** 電腦關機、休眠、網路中斷或 OpenD 停止會影響執行；本專案不保證補齊遺失的即時窗口。

`requirements.txt` 記錄 Python 依賴；`.state/` 保存私有即時輸入與暫存並被 gitignore 排除。API 權杖、帳戶、交易資料及本機登入憑證不得提交。

```bash
# Windows 本機的專用 Python
.venv/Scripts/python.exe radar.py gate
.venv/Scripts/python.exe radar.py scan --diagnostic
.venv/Scripts/python.exe radar.py tick
.venv/Scripts/python.exe -m pytest -q
```

排程研究指令見 `prompts/radar.md`；禁止使用任何下單、撤單、改單或解鎖交易 API。
