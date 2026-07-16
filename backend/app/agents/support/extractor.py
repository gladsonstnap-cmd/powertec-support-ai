import re


DEVICE_RE = re.compile(r"\b(caixa|terminal|servidor|pdv)[\s\-]*(\d{1,3})?\b", re.IGNORECASE)
VERSION_RE = re.compile(r"\b(?:vers[aã]o|v\.?)\s*([0-9]+(?:\.[0-9]+){0,3})\b", re.IGNORECASE)
ERROR_RE = re.compile(r"(?:erro|mensagem|rejei[cç][aã]o)\s*[:\-]?\s*([^\n.]{3,160})", re.IGNORECASE)


def extract_context(text: str) -> dict:
    device = ""
    match = DEVICE_RE.search(text)
    if match:
        suffix = match.group(2) or ""
        device = f"{match.group(1).upper()}-{int(suffix):02d}" if suffix.isdigit() else match.group(1).upper()
    version = ""
    if version_match := VERSION_RE.search(text):
        version = version_match.group(1)
    error_message = ""
    if error_match := ERROR_RE.search(text):
        error_message = error_match.group(1).strip()
    product = ""
    normalized = text.lower()
    if "nfce" in normalized or "nfc-e" in normalized:
        product = "Emissor NFC-e"
    elif "tef" in normalized:
        product = "TEF"
    elif "pdv" in normalized or "caixa" in normalized:
        product = "PDV PowerVarejo"
    elif "retaguarda" in normalized or "servidor" in normalized:
        product = "Retaguarda PowerVarejo"
    return {
        "device": device,
        "version": version,
        "error_message": error_message,
        "product": product,
    }


def missing_information_for(text: str, extracted: dict) -> list[str]:
    missing = []
    normalized = text.lower()
    if not extracted.get("device") and any(term in normalized for term in ["caixa", "terminal", "pdv", "impressora"]):
        missing.append("equipamento")
    if not extracted.get("error_message") and any(term in normalized for term in ["erro", "rejeitada", "nao abre", "não abre"]):
        missing.append("mensagem de erro")
    if "todos" not in normalized and "quantos" not in normalized:
        missing.append("impacto")
    if not extracted.get("version"):
        missing.append("versao")
    return missing[:4]
