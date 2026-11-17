from etl.embed import embedding_hash, embedding_text


def test_embedding_text_uses_document_format_with_aliases():
    text = embedding_text("software developer", "Writes software.", ["application developer", "programmer"])
    assert text == "title: software developer | text: Writes software. Also known as: application developer, programmer"


def test_embedding_text_without_description_or_aliases():
    assert embedding_text("Python", None, None) == "title: Python | text: none"
    assert embedding_text("Python", "   ", []) == "title: Python | text: none"


def test_embedding_text_caps_aliases():
    text = embedding_text("x", None, [f"alias{i}" for i in range(10)])
    assert text.endswith("alias0, alias1, alias2, alias3, alias4")


def test_hash_changes_with_text_and_model():
    base = embedding_hash("gemini-embedding-2", "title: a | text: none")
    assert base == embedding_hash("gemini-embedding-2", "title: a | text: none")
    assert base != embedding_hash("gemini-embedding-2", "title: b | text: none")
    assert base != embedding_hash("gemini-embedding-001", "title: a | text: none")
    assert len(base) == 64
