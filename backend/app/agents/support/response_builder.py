def next_question(missing_information: list[str], previous_questions: list[str], asked_count: int = 0) -> str | None:
    if asked_count >= 3:
        return "Posso encaminhar para um tecnico humano para continuar a verificacao?"
    catalog = {
        "impacto": "Em quantos caixas o problema ocorre?",
        "mensagem de erro": "Qual mensagem aparece na tela?",
        "servidor": "O servidor esta ligado?",
        "internet": "A internet esta funcionando?",
        "versao": "Qual e a versao do sistema?",
        "equipamento": "Qual equipamento apresenta o problema?",
        "nfce": "A NFC-e apresenta algum codigo de rejeicao?",
    }
    used = {item.strip().lower() for item in previous_questions}
    for item in missing_information:
        question = catalog.get(item)
        if question and question.lower() not in used:
            return question
    return None
