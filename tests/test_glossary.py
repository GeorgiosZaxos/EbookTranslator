from ebook_translator.translation.glossary import Glossary


def test_glossary_protect_restore(tmp_path):
    path = tmp_path / "glossary.txt"
    path.write_text("Hobbit=Χόμπιτ\n", encoding="utf-8")
    glossary = Glossary(str(path))
    protected, mapping = glossary.protect("The Hobbit")
    assert "Hobbit" not in protected
    assert glossary.restore(protected, mapping) == "The Χόμπιτ"


def test_selects_glossary_for_each_direction():
    from ebook_translator.translation.glossary import select_glossary_path

    assert select_glossary_path("English", "Greek", "en-el.txt", "el-en.txt") == "en-el.txt"
    assert select_glossary_path("Greek", "English", "en-el.txt", "el-en.txt") == "el-en.txt"
    assert select_glossary_path("Auto-detect", "Greek", "en-el.txt", "el-en.txt") == "en-el.txt"
    assert select_glossary_path("Auto-detect", "English", "en-el.txt", "el-en.txt") == "el-en.txt"


def test_other_language_pair_retains_legacy_glossary():
    from ebook_translator.translation.glossary import select_glossary_path

    assert select_glossary_path("French", "Greek", "en-el.txt", "el-en.txt", "legacy.txt") == "legacy.txt"
