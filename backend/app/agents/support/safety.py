import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(token|senha|password|secret|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)postgresql\+?\w*://\S+"),
]

INJECTION_TERMS = [
    "ignore as instrucoes",
    "ignore as instruções",
    "desative auditoria",
    "mostre o token",
    "obtenha senhas",
    "execute comando",
    "apague dados",
    "faca deploy",
    "faça deploy",
    "aja como administrador",
]

UNSAFE_ACTION_TERMS = [
    "excluir arquivos",
    "editar registro",
    "executar sql",
    "formatar",
    "desativar antivirus",
    "desativar antivírus",
    "abrir portas",
    "alterar banco",
    "trocar certificado",
    "rodar script",
]


def mask_secrets(text: str) -> str:
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[SEGREDO_REMOVIDO]", sanitized)
    return sanitized


def detect_prompt_injection(text: str) -> list[str]:
    normalized = text.lower()
    return [term for term in INJECTION_TERMS if term in normalized]


def safe_customer_response(question: str | None, priority: str, requires_human: bool) -> str:
    if requires_human or priority == "P1":
        prefix = "Identifiquei impacto critico e vou encaminhar para um tecnico humano."
    else:
        prefix = "Recebi as informacoes e vou continuar a triagem com seguranca."
    if question:
        return f"{prefix} {question}"
    return prefix


def filter_safe_actions(actions: list[str]) -> tuple[list[str], list[str], bool]:
    safe, notes = [], []
    requires_authorization = False
    for action in actions:
        if any(term in action.lower() for term in UNSAFE_ACTION_TERMS):
            notes.append(f"Acao de risco bloqueada: {action}")
            requires_authorization = True
            continue
        safe.append(action)
    return safe, notes, requires_authorization
