from datetime import datetime
import pytest
import radar

SLOT='2026-10-05T22:00:00+08:00'
ENTRY='## 22:00 台北／10:00 ET｜能源股同步反彈\n市場一句話：能源股同步反彈。\n\n🟢 能源｜79/100；XLE +0.707%；代表股4/4上漲。\n\n<details><summary>本輪數據與查核明細</summary>\n\n查核證據\n\n</details>\n'


def test_new_style_keeps_hotspot_visible_and_has_only_one_title():
    result=radar.append_slot('# 每日報告\n',SLOT,ENTRY)
    block=result.split('<!-- radar-slot:',1)[1]
    visible=block.split('<details>',1)[0]
    assert '🟢 能源｜79/100' in visible
    assert block.count('## 22:00 台北／10:00 ET｜')==1
    assert '查核證據' not in visible


def test_navigation_is_at_top_and_old_retry_cannot_replace_latest():
    first=radar.append_slot('# 每日報告\n',SLOT,ENTRY)
    second=radar.append_slot(first,'2026-10-05T22:10:00+08:00','市場一句話：本輪沒有新異動。')
    assert second.index('radar-latest:start')<second.index('radar-slot:')
    assert '#radar-2026-10-05t2210000800' in second
    assert radar.append_slot(second,SLOT,ENTRY)==second


def test_out_of_order_publish_navigation_points_to_latest_not_last_append():
    newest=radar.append_slot('# 每日報告\n','2026-10-05T22:10:00+08:00','市場一句話：新輪。')
    late=radar.append_slot(newest,SLOT,ENTRY)
    assert '[跳至最新一輪](#radar-2026-10-05t2210000800)' in late


def test_partial_data_title_never_says_no_credible_hotspots():
    info={'slot':SLOT,'market_state':'正常盤'}
    result={'status':'partial','errors':[{'error':'permission denied'}],'rows':[], 'coverage':{'usable_count':14,'requested_count':29}}
    text=radar.render_quiet_report(info,result)
    assert '｜資料不足' in text.splitlines()[0]
    visible=text.split('<details>',1)[0]
    assert '最近 10 分鐘沒有發現具有足夠可信度的市場熱點。' not in text
    assert 'permission denied' not in visible
    assert 'permission denied' in text


def test_summary_not_taken_from_technical_warning_inside_details():
    entry=ENTRY.replace('查核證據','資料不足或未確認原因不能稱市場平靜。')
    text=radar.append_slot('# 每日報告\n',SLOT,entry)
    assert '｜能源股同步反彈' in text
    assert '｜本輪資料不足' not in text
