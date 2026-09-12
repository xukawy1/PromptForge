from app.services.collector_service import CollectorService

def test_normalize_url_removes_tracking_and_fragment():
    assert CollectorService.normalize_url('Example.COM/a?utm_source=x&b=2#top') == 'https://example.com/a?b=2'

def test_hash_is_stable():
    assert CollectorService.hash_bytes(b'abc') == CollectorService.hash_bytes(b'abc')
