import pytest
from app.core.exceptions import ConfigurationError
from app.services.encryption_service import EncryptionService


def test_encrypt_decrypt_string_roundtrip(encryption_service: EncryptionService):
    original = "super_secret_refresh_token_12345"
    encrypted = encryption_service.encrypt_string(original)

    assert encrypted != original
    assert len(encrypted) > len(original)

    decrypted = encryption_service.decrypt_string(encrypted)
    assert decrypted == original


def test_encrypt_decrypt_dict_roundtrip(encryption_service: EncryptionService):
    credentials = {
        "access_token": "ya29.a0AfH6SM...",
        "refresh_token": "1//04...",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly",
    }

    token = encryption_service.encrypt_dict(credentials)
    assert isinstance(token, str)
    assert "ya29" not in token  # Ensure plaintext token is not visible in ciphertext

    decrypted = encryption_service.decrypt_dict(token)
    assert decrypted == credentials
    assert decrypted["access_token"] == credentials["access_token"]
    assert decrypted["refresh_token"] == credentials["refresh_token"]


def test_tampered_ciphertext_fails(encryption_service: EncryptionService):
    encrypted = encryption_service.encrypt_string("secret_value")
    # Tamper with the ciphertext (change middle character)
    tampered = encrypted[:10] + ("X" if encrypted[10] != "X" else "Y") + encrypted[11:]

    with pytest.raises(ValueError, match="Decryption failed"):
        encryption_service.decrypt_string(tampered)


def test_unique_ciphertexts_for_same_plaintext(encryption_service: EncryptionService):
    plaintext = "identical_token"
    c1 = encryption_service.encrypt_string(plaintext)
    c2 = encryption_service.encrypt_string(plaintext)

    # Fernet generates fresh IV/timestamp each time, so ciphertexts should differ
    assert c1 != c2
    assert encryption_service.decrypt_string(c1) == plaintext
    assert encryption_service.decrypt_string(c2) == plaintext


def test_passphrase_key_derivation():
    # Passphrase of arbitrary length
    svc1 = EncryptionService("short-passphrase")
    svc2 = EncryptionService("short-passphrase")

    encrypted = svc1.encrypt_string("hello world")
    assert svc2.decrypt_string(encrypted) == "hello world"


def test_empty_key_raises_error():
    with pytest.raises(ConfigurationError):
        EncryptionService("")
