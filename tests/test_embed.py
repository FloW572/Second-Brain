from app.ingest.embed import to_vector_literal


def test_vector_literal_format():
    assert to_vector_literal([0.5, -1.0]) == "[0.50000000,-1.00000000]"


def test_vector_literal_empty():
    assert to_vector_literal([]) == "[]"


def test_vector_literal_no_spaces():
    lit = to_vector_literal([1.0, 2.0, 3.0])
    assert " " not in lit
    assert lit.startswith("[") and lit.endswith("]")
