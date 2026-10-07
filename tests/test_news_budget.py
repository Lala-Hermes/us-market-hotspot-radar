"""Guard the unattended prompt against unbounded news/login waits."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_news_failure_has_bounded_calls_and_publish_fallback():
    prompt = (ROOT / 'prompts/radar.md').read_text(encoding='utf-8')
    for requirement in (
        'timeout_s=30',
        '新聞查核總預算120秒',
        '每來源只嘗試一次，不重試',
        '禁止登入、呼叫vault、等待使用者',
        'profile locked',
        '新聞受阻仍須發布行情與限制報告',
    ):
        assert requirement in prompt
