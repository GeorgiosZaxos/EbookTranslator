from ebook_translator.persistence.cache import TranslationCache


def test_memory_cache_round_trip():
    cache = TranslationCache()
    key = cache.make_key("Hello", "English", "Greek", "provider", "model")
    assert cache.get(key) is None
    cache.put(key, "Hello", "Γεια", "provider", "model", "English", "Greek")
    assert cache.get(key) == "Γεια"
