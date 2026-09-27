import base64
import hashlib
import json
import logging
from typing import Any, Dict
from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class EncryptionService:
    """
    Symmetric encryption service for encrypting and decrypting sensitive credentials at rest.
    Uses AES-128-CBC with HMAC-SHA256 authenticated encryption via Fernet.
    """

    def __init__(self, key: str):
        if not key:
            raise ConfigurationError("ENCRYPTION_KEY must be provided for secure credential storage.")

        self._fernet = self._initialize_fernet(key)

    @staticmethod
    def _initialize_fernet(raw_key: str) -> Fernet:
        """
        Derives or parses a valid 32-byte URL-safe base64-encoded Fernet key.
        Accepts either an existing Fernet key or an arbitrary passphrase.
        """
        raw_bytes = raw_key.strip().encode("utf-8")

        # Check if already a valid 32-byte Fernet key (44 base64 chars)
        if len(raw_bytes) == 44:
            try:
                decoded = base64.urlsafe_b64decode(raw_bytes)
                if len(decoded) == 32:
                    return Fernet(raw_bytes)
            except Exception:
                pass

        # Otherwise derive a deterministic 32-byte key via SHA-256
        digest = hashlib.sha256(raw_bytes).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        return Fernet(fernet_key)

    def encrypt_string(self, plaintext: str) -> str:
        """Encrypt a UTF-8 string into a base64 ciphertext token."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt_string(self, token: str) -> str:
        """Decrypt a ciphertext token back into a UTF-8 string."""
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            logger.error("Failed to decrypt token: InvalidToken or ciphertext tampering.")
            raise ValueError("Decryption failed: Token is invalid, corrupted, or tampered with.") from exc

    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """Serialize a dictionary to JSON and encrypt it."""
        serialized = json.dumps(data, separators=(",", ":"), sort_keys=True)
        return self.encrypt_string(serialized)

    def decrypt_dict(self, token: str) -> Dict[str, Any]:
        """Decrypt a ciphertext token and deserialize back to a dictionary."""
        decrypted_json = self.decrypt_string(token)
        return json.loads(decrypted_json)
