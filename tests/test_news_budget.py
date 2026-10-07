"""Guard the unattended prompt against unbounded news/login waits."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_news_failure_has_bounded_calls_and_publish_fallback():
    prompt = (ROOT / 'prompts/radar.md').read_text(encoding='utf-8')
    for requirement in (
        '禁止使用瀏覽器工具',
        '只使用金十MCP',
        '不啟動網頁備援',
        '新聞查核總預算120秒',
        '每來源只嘗試一次，不重試',
        '禁止登入、呼叫vault、等待使用者',
        '新聞受阻仍須發布行情與限制報告',
    ):
        assert requirement in prompt
    for retired_collection in ('https://news.futunn.com/main/live', 'https://www.jin10.com', 'flashList', '__NUXT__', '.flash-text', 'timeout_s=30'):
        assert retired_collection not in prompt
