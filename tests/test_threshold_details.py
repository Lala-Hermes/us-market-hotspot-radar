from test_publish import publication_repo, run_git

import radar
import radar_market as market


def row(ticker, move=.69546):
    return dict(ticker=ticker, status='ok', return_10m_pct=move,
                previous_3_10m_returns_pct=[.29722,.45763,.1],
                volume_10m=10000, traded_minutes=10, volume_ratio_10m=2,
                relative_spy_pp=.6, relative_qqq_pp=.7, acceleration_pp=.3,
                baseline_source='preceding_close')


def test_quiet_report_explains_fixed_watch_below_dynamic_threshold():
    result={'status':'ok','rows':{'IGV':row('IGV')},'candidates':[]}
    text=radar.render_quiet_report({'slot':'2026-10-06T22:30:00+08:00'}, result)
    visible,details=text.split('<details>',1)
    assert '動態價格門檻' not in visible
    assert 'SOXX' in details and 'SMH' in details and 'IGV' in details
    assert '0.74305%' in details and '+0.69546%' in details
    assert '價格未達門檻' in details
    assert '未取得掃描資料' in details


def test_publisher_adds_snapshot_explanation_to_agent_report(publication_repo):
    import json
    root,remote,slot,report,scan=publication_repo
    data=json.loads(scan.read_text(encoding='utf-8'))
    data.update(rows={'IGV':row('IGV')},candidates=[])
    scan.write_text(json.dumps(data),encoding='utf-8')
    report.write_text('## 21:40 台北／09:40 ET｜測試熱點\n市場一句話：保留主文。\n\n<details><summary>本輪數據與查核明細</summary>\n既有明細\n</details>\n',encoding='utf-8')
    first=radar.publish(slot,report)
    second=radar.publish(slot,report)
    text=run_git(remote,'show','main:reports/2026-10-05.md').decode('utf-8')
    assert first['verified'] and first['commit']==second['commit']
    assert text.count('<!-- radar-threshold-details -->')==1
    assert '0.74305%' in text
    assert '既有明細' in text
    assert '動態價格門檻' not in text.split('<details>',1)[0]


def test_unknown_cluster_exclusion_does_not_invent_a_cause():
    from radar_explain import threshold_details
    text=threshold_details({'rows':{'IGV':row('IGV',1)},'candidates':[]})
    assert '聚類未入選；快照未提供確切排除原因' in text
    assert '缺樣本／反向樣本降分或排序限制' not in text


def test_opposite_sample_reason_is_explicit():
    from radar_explain import threshold_details
    rows={'IGV':row('IGV',1)}
    extra={t:row(t,-1) for t in ('CRM','NOW','SNOW')}
    text=threshold_details({'rows':rows,'constituents':extra,'candidates':[]})
    assert '代表股反向多數（3/3）' in text


def test_explanation_handles_invalid_data_and_is_idempotent():
    from radar_explain import add_threshold_details
    entry='主文\n<details><summary>明細</summary>\n原始明細\n</details>\n'
    snapshot={'rows':{'IGV':dict(ticker='IGV',status='error',return_10m_pct=None)},'candidates':[]}
    text=add_threshold_details(entry,snapshot)
    assert '資料不足／掃描受阻' in text
    assert add_threshold_details(text,snapshot)==text


def test_price_threshold_equality_and_other_gates():
    r=row('IGV',.74305)
    gates=market.selection_conditions(r,'software')
    assert gates['price_pass'] and gates['active'] and gates['confirmed']
    r.update(volume_10m=1,volume_ratio_10m=1,relative_spy_pp=0,acceleration_pp=0)
    gates=market.selection_conditions(r,'software')
    assert not gates['active'] and not gates['confirmed']
