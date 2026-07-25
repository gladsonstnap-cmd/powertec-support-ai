from app.services.diagnostic_engine.knowledge_models import DiagnosticQuestion, KnowledgeIncident


class QuestionSelector:
    def select_next_question(
        self,
        incident: KnowledgeIncident,
        known_information: dict[str, object] | None = None,
        asked_question_ids: set[str] | None = None,
    ) -> DiagnosticQuestion | None:
        known_information = known_information or {}
        asked_question_ids = asked_question_ids or set()

        candidates = [
            question
            for question in incident.questions
            if question.id not in asked_question_ids and not self._has_known_value(question, known_information)
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda question: (not question.required, question.priority, question.id))
        return candidates[0]

    @staticmethod
    def _has_known_value(question: DiagnosticQuestion, known_information: dict[str, object]) -> bool:
        value = known_information.get(question.field)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True
