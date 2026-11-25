"""Task 5.1: the sending-number encryption round-trips and fails closed on the wrong key (file 07 §3, D-021)."""
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app import crypto

KEY = Fernet.generate_key().decode()
PHONE = "923001234567"


def test_round_trip():
    assert crypto.decrypt(KEY, crypto.encrypt(KEY, PHONE)) == PHONE


def test_ciphertext_hides_the_number():
    token = crypto.encrypt(KEY, PHONE)
    assert PHONE not in token and token != PHONE


def test_wrong_key_cannot_decrypt():
    token = crypto.encrypt(KEY, PHONE)
    with pytest.raises(InvalidToken):
        crypto.decrypt(Fernet.generate_key().decode(), token)
