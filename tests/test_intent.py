from nltest.matcher.intent import parse_query_into_clauses


def test_simple_query_returns_single_main_clause():
    clauses = parse_query_into_clauses("test recording")
    assert len(clauses) == 1
    assert clauses[0].role == "main"
    assert clauses[0].text == "test recording"


def test_after_connector_makes_right_side_the_prerequisite():
    clauses = parse_query_into_clauses("test save employment after importing")
    assert [c.role for c in clauses] == ["prerequisite", "main"]
    assert clauses[0].text == "importing"
    assert clauses[1].text == "test save employment"


def test_once_connector_behaves_like_after():
    clauses = parse_query_into_clauses("run the checkout flow once login succeeds")
    assert clauses[0].role == "prerequisite"
    assert clauses[0].text == "login succeeds"
    assert clauses[1].text == "run the checkout flow"


def test_before_connector_makes_left_side_the_prerequisite():
    clauses = parse_query_into_clauses("import employment data before saving a new record")
    assert clauses[0].role == "prerequisite"
    assert clauses[0].text == "import employment data"
    assert clauses[1].role == "main"
    assert clauses[1].text == "saving a new record"


def test_then_connector_runs_left_first():
    clauses = parse_query_into_clauses("import the csv then save the employment record")
    assert clauses[0].text == "import the csv"
    assert clauses[0].role == "prerequisite"
    assert clauses[1].text == "save the employment record"


def test_connector_with_empty_side_falls_back_to_single_clause():
    clauses = parse_query_into_clauses("after")
    assert len(clauses) == 1
    assert clauses[0].role == "main"
