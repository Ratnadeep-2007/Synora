import time
import pytest
from app.core.exceptions import InvalidOAuthStateException
from app.core.security import OAuthStateManager


def test_generate_and_verify_valid_state():
    user_id = "usr_test_123"
    return_to = "http://localhost:3000/integrations"

    state, nonce = OAuthStateManager.generate_state(
        user_id=user_id,
        return_to=return_to,
        extra={"custom_param": "abc"},
    )

    assert state is not None
    assert nonce is not None
    assert "." in state

    # Verify state with correct nonce
    payload = OAuthStateManager.verify_state(state, cookie_nonce=nonce)
    assert payload["user_id"] == user_id
    assert payload["return_to"] == return_to
    assert payload["extra"]["custom_param"] == "abc"
    assert payload["nonce"] == nonce


def test_tampered_state_payload_fails():
    state, nonce = OAuthStateManager.generate_state(user_id="usr_original")
    parts = state.split(".")

    # Tamper with the payload part
    tampered_payload = parts[0][:-2] + "AA"
    tampered_state = f"{tampered_payload}.{parts[1]}"

    with pytest.raises(InvalidOAuthStateException, match="Possible CSRF attack"):
        OAuthStateManager.verify_state(tampered_state, cookie_nonce=nonce)


def test_tampered_state_signature_fails():
    state, nonce = OAuthStateManager.generate_state(user_id="usr_original")
    parts = state.split(".")

    # Tamper with the signature
    tampered_signature = parts[1][:-2] + "ZZ"
    tampered_state = f"{parts[0]}.{tampered_signature}"

    with pytest.raises(InvalidOAuthStateException, match="Possible CSRF attack"):
        OAuthStateManager.verify_state(tampered_state, cookie_nonce=nonce)


def test_expired_state_fails():
    # Generate state with -1 second expiry
    state, nonce = OAuthStateManager.generate_state(
        user_id="usr_test",
        expire_seconds=-10,
    )

    with pytest.raises(InvalidOAuthStateException, match="OAuth state has expired"):
        OAuthStateManager.verify_state(state, cookie_nonce=nonce)


def test_cookie_nonce_mismatch_fails():
    state, nonce = OAuthStateManager.generate_state(user_id="usr_test")

    with pytest.raises(InvalidOAuthStateException, match="nonce does not match session cookie"):
        OAuthStateManager.verify_state(state, cookie_nonce="wrong-attacker-nonce")


def test_missing_state_fails():
    with pytest.raises(InvalidOAuthStateException, match="missing"):
        OAuthStateManager.verify_state(None)

    with pytest.raises(InvalidOAuthStateException, match="missing"):
        OAuthStateManager.verify_state("")


def test_malformed_state_fails():
    with pytest.raises(InvalidOAuthStateException, match="Invalid OAuth state structure"):
        OAuthStateManager.verify_state("just-a-single-token-without-dot")
