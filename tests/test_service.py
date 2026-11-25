from ebook_translator.translation.service import split_text


def test_split_text_preserves_content():
    text = ("A sentence. " * 100) + "\n\n" + ("Another paragraph. " * 100)
    chunks = split_text(text, 250)
    assert "".join(chunks) == text
    assert all(chunks)


def test_identical_concurrent_requests_are_coalesced():
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from ebook_translator.persistence.cache import TranslationCache
    from ebook_translator.translation.service import TranslationService
    from ebook_translator.translation.glossary import Glossary
    from ebook_translator.translation.providers import TranslationProvider

    class CountingProvider(TranslationProvider):
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()

        def translate(self, text, source_language, target_language, context=""):
            with self.lock:
                self.calls += 1
            time.sleep(0.05)
            return f"translated:{text}"

    provider = CountingProvider()
    service = TranslationService(
        provider=provider,
        cache=TranslationCache(),
        endpoint="test://endpoint",
        model="test-model",
        source_language="English",
        target_language="Greek",
        glossary=Glossary(),
    )
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: service.translate("same phrase"), range(5)))

    assert results == ["translated:same phrase"] * 5
    assert provider.calls == 1
