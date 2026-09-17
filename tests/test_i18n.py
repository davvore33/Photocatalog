from photocatalog.viewer import i18n


def test_translate_it_and_en_differ():
    it_text = i18n.translate("it", "scan.stop_button")
    en_text = i18n.translate("en", "scan.stop_button")
    assert it_text != en_text
    assert it_text and en_text


def test_translate_interpolates_kwargs():
    text = i18n.translate("en", "index.result_count", n=5)
    assert text == "5 images"


def test_translate_falls_back_to_default_lang_for_unknown_lang():
    assert i18n.translate("fr", "scan.go_button") == i18n.translate("it", "scan.go_button")


def test_translate_unknown_key_returns_key_itself():
    assert i18n.translate("en", "totally.unknown.key") == "totally.unknown.key"


def test_all_languages_have_the_same_keys():
    it_keys = set(i18n.TRANSLATIONS["it"].keys())
    en_keys = set(i18n.TRANSLATIONS["en"].keys())
    assert it_keys == en_keys
