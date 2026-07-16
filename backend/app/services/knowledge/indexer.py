import hashlib
import math
import re


TOKEN_RE = re.compile(r"[a-zA-Z0-9À-ÿ-]{3,}")


def keywords_for(text: str) -> list[str]:
    tokens = [token.lower() for token in TOKEN_RE.findall(text)]
    seen = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:40]


def embedding_for(text: str, dimensions: int = 16) -> list[float]:
    vector = [0.0] * dimensions
    for token in keywords_for(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dimensions
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    return sum(left[i] * right[i] for i in range(length))
