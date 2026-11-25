from ebook_translator.text_utils import decode_entities, safe_filename


def test_decode_apostrophe_entity_without_semicolon():
    assert decode_entities("L&#39;été") == "L'été"


def test_decode_double_encoded_apostrophe_entity():
    assert decode_entities("L&amp;#39;été") == "L'été"


def test_safe_filename_removes_windows_forbidden_characters():
    assert safe_filename('A/B:C*D? "E"') == "A_B_C_D_ _E_"


def test_safe_filename_handles_reserved_device_names():
    assert safe_filename("CON") == "_CON"
