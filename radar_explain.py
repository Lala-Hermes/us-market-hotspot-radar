"""Deterministic report explanation; never changes anomaly selection."""
from statistics import median
from radar_market import BROAD, CLUSTERS, CONSTITUENTS, _valid, selection_conditions

MARKER='<!-- radar-threshold-details -->'
WATCH=('SOXX','SMH','IGV')


def threshold_details(snapshot):
    rows=snapshot.get('rows',{})
    if not isinstance(rows,dict):
        rows={r.get('ticker',r.get('symbol')):r for r in rows}
    selected={c['cluster']:c for c in snapshot.get('candidates',[])}
    tickers=list(dict.fromkeys(list(WATCH)+list(rows)))
    lines=[MARKER,'### 固定關注與動態門檻',
           'SOXX／SMH 為半導體 ETF 代理，非 SOX 指數；IGV 為軟體 ETF。固定顯示不代表熱點。',
           '價格門檻＝max(固定底線, 前三個10分鐘報酬絕對值中位數 × 2.5)，以未四捨五入數值比較。價格通過不等於入選；另檢查成交活躍度、量比／相對強弱／加速度及代表股樣本。',
           '', '|標的|10分鐘報酬|相對SPY（百分點）|相對QQQ（百分點）|動態價格門檻（絕對值）|價格條件|篩選結果／未入選原因|',
           '|---|---:|---:|---:|---:|---|---|']
    def number(value, suffix=''):
        return 'NA' if value is None else f'{value:+.5f}{suffix}'
    for ticker in tickers:
        row=rows.get(ticker)
        name=next((n for n,members in CLUSTERS.items() if ticker in members),None)
        if row is None:
            cells=['NA']*4+['未知','未取得掃描資料']
        elif not _valid(row) or name is None:
            cells=[number(row.get('return_10m_pct'),'%'),number(row.get('relative_spy_pp')),number(row.get('relative_qqq_pp')),'NA','未知','資料不足／掃描受阻；不判定無異常']
        else:
            members=[rows[t] for t in CLUSTERS[name] if _valid(rows.get(t))]
            floor=.25 if any(r['ticker'] in BROAD for r in members) else (.6 if name=='crypto' else .4)
            gates=selection_conditions(row,name,floor)
            reasons=[]
            if not gates['price_pass']:reasons.append('價格未達門檻')
            if not gates['active']:reasons.append('成交活躍度不足')
            if not gates['confirmed']:reasons.append('量比／相對強弱／加速度均未確認')
            candidate=selected.get(name)
            if candidate:
                reasons.append('聚類入選'+('（自身觸發）' if ticker in candidate.get('triggered_members',[]) else '（同聚類成員，自身未觸發）'))
            elif not reasons:
                move=median(r['return_10m_pct'] for r in members)
                mixed=any(r['return_10m_pct']>=floor for r in members) and any(r['return_10m_pct']<=-floor for r in members)
                extra=snapshot.get('constituents',{})
                sample=[extra[t] for t in CONSTITUENTS.get(name,[]) if _valid(extra.get(t))]
                opposite=sum(r['return_10m_pct']*move<0 for r in sample)
                if not mixed and len(sample)>=2 and opposite/len(sample)>.5:
                    reasons.append(f'代表股反向多數（{opposite}/{len(sample)}）；聚類未入選')
                else:
                    reasons.append('單標的條件通過；聚類未入選；快照未提供確切排除原因（非價格未達）')
            cells=[number(row.get('return_10m_pct'),'%'),number(row.get('relative_spy_pp')),number(row.get('relative_qqq_pp')),f"{gates['threshold']:.5f}%",'通過' if gates['price_pass'] else '未通過','；'.join(reasons)]
        lines.append('|'+ticker+'|'+'|'.join(cells)+'|')
    lines.extend(['','NA 表示未取得有效資料，不是零；未入選不代表全天弱勢或沒有新聞。'])
    btc=snapshot.get('btc')
    if btc:
        lines.extend(['','### BTC/USD 獨立跨資產觀察（非IBIT）'])
        if btc.get('status')=='ok':
            volume=btc.get('volume_10m')
            amount='NA' if volume is None else f'{volume:.5f} BTC'
            lines.append(f"Futu現貨幣對10分鐘 {number(btc.get('return_10m_pct'),'%')}；窗口量 {amount}；量比 {number(btc.get('volume_ratio_10m'))}；完成分鐘 {btc.get('completed_bars','NA')}/10、成交分鐘 {btc.get('traded_minutes','NA')}/10。")
            lines.append(f"來源時間由 unix epoch 轉換；最後完成分鐘 {btc.get('last_completed_bar','未知')}。不計入29檔ETF覆蓋率，不代表全球Bitcoin成交量；供應商延遲未獨立確認。")
        else:
            lines.append('本輪資料不足／掃描受阻：'+btc.get('reason','未知原因')+'；未納入訊號。')
    return '\n'.join(lines)+'\n'


def add_threshold_details(entry,snapshot):
    if MARKER in entry:
        return entry
    detail=threshold_details(snapshot)
    position=entry.rfind('</details>')
    if position>=0:
        return entry[:position]+'\n'+detail+'\n'+entry[position:]
    return entry.rstrip()+'\n\n<details><summary>本輪動態門檻與固定關注</summary>\n\n'+detail+'\n</details>\n'
