from app.services.pathutil import normalize_path_for_discovery, path_matches_template


def test_normalize_dynamic_segments() -> None:
    assert normalize_path_for_discovery("/users/123") == "/users/{id}"
    assert normalize_path_for_discovery("/orders/550e8400-e29b-41d4-a716-446655440000") == "/orders/{uuid}"


def test_template_matching() -> None:
    assert path_matches_template("/users/99", "/users/{userId}")
    assert not path_matches_template("/users/99/details", "/users/{userId}")
