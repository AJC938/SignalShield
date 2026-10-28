"""Systematic even-parity Hamming(7,4), positions numbered 1..7."""
import numpy as np


def encode(bits: object) -> np.ndarray:
    b = np.asarray(bits, dtype=np.uint8)
    if b.ndim != 1 or b.size % 4 or not np.all((b == 0) | (b == 1)):
        raise ValueError("Hamming input must be binary and divisible into 4-bit words")
    d = b.reshape(-1, 4)
    d1, d2, d3, d4 = d.T
    return np.stack((d1 ^ d2 ^ d4, d1 ^ d3 ^ d4, d1, d2 ^ d3 ^ d4, d2, d3, d4), axis=1).reshape(-1)


def decode(bits: object) -> tuple[np.ndarray, int]:
    b = np.asarray(bits, dtype=np.uint8)
    if b.ndim != 1 or b.size % 7 or not np.all((b == 0) | (b == 1)):
        raise ValueError("Hamming input must be binary and divisible into 7-bit words")
    words = b.reshape(-1, 7).copy()
    corrected = 0
    for w in words:
        p1, p2, _, p4, _, _, _ = w
        syndrome = int(p1 ^ w[2] ^ w[4] ^ w[6]) | (int(p2 ^ w[2] ^ w[5] ^ w[6]) << 1) | (int(p4 ^ w[4] ^ w[5] ^ w[6]) << 2)
        if syndrome:
            w[syndrome - 1] ^= 1
            corrected += 1
    return words[:, [2, 4, 5, 6]].reshape(-1), corrected
