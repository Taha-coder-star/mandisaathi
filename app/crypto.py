"""Reversible encryption of the sending phone number (task 5.1, file 07 §3).

Ingest (task 3.1) stores a *hash* of every number for analysis; you cannot send to a hash. File 07 §3 keeps the
number two ways: a salted hash (analysis) and an *encrypted* copy that only the sending code can open. This module is
that encrypted copy: Fernet (AES-128-CBC + HMAC-SHA256, authenticated) keyed by WA_NUMBER_ENC_KEY. The web role
encrypts the sender's number into the stored payload (`from_enc`); the worker decrypts it just before a send.

Choices: DECISIONS.md D-021. The key lives only in `.env` (never committed). It must not change once numbers are
stored, or old ciphertext stops opening. A wrong/missing key raises, so a reply can never go out to a number we could
not verify.
"""
from cryptography.fernet import Fernet


def encrypt(key: str, plaintext: str) -> str:
    """Fernet token (url-safe text) for plaintext. `key` is a 44-char url-safe base64 key (Fernet.generate_key())."""
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()


def decrypt(key: str, token: str) -> str:
    """Inverse of encrypt. Raises cryptography.fernet.InvalidToken on a wrong key or tampered token."""
    return Fernet(key.encode()).decrypt(token.encode()).decode()
