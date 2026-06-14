from app.auth.passwords import hash_password, verify_password


def test_hash_then_verify_ok():
    assert verify_password("correct horse", hash_password("correct horse"))


def test_verify_wrong_password():
    assert not verify_password("wrong", hash_password("correct horse"))


def test_hashes_are_salted_unique():
    assert hash_password("same") != hash_password("same")  # random per-call salt
