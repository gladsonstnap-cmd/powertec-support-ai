from dataclasses import replace

from app.services.diagnostic_engine.conversation_models import (
    ConversationCommand,
    ConversationInput,
    ConversationResponse,
)
from app.services.diagnostic_engine.normalization import normalize_text
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import (
    DiagnosticSession,
    DiagnosticSessionStatus,
    SessionTurnResult,
)


HELP_MESSAGE = """Você pode:

• descrever o problema;

• responder às perguntas;

• solicitar um atendente;

• reiniciar o diagnóstico;

• cancelar o atendimento;

• consultar o status."""

_COMMANDS = {
    "status": ConversationCommand.STATUS,
    "cancelar": ConversationCommand.CANCEL,
    "encerrar": ConversationCommand.CANCEL,
    "reiniciar": ConversationCommand.RESTART,
    "comecar novamente": ConversationCommand.RESTART,
    "humano": ConversationCommand.ESCALATE,
    "atendente": ConversationCommand.ESCALATE,
    "ajuda": ConversationCommand.HELP,
    "help": ConversationCommand.HELP,
}

_FINISHED_STATUSES = {
    DiagnosticSessionStatus.ESCALATED,
    DiagnosticSessionStatus.COMPLETED,
    DiagnosticSessionStatus.CANCELLED,
    DiagnosticSessionStatus.FAILED,
}


class DiagnosticConversationEngine:
    """Thin deterministic conversation adapter over DiagnosticSessionEngine."""

    def __init__(self, session_engine: DiagnosticSessionEngine | None = None) -> None:
        self.session_engine = session_engine if session_engine is not None else DiagnosticSessionEngine()

    def start_conversation(
        self,
        message: str,
        context: DiagnosticContext | None = None,
    ) -> ConversationResponse:
        return self.process(ConversationInput(message=message, context=context))

    def continue_conversation(
        self,
        session: DiagnosticSession,
        message: str,
        context: DiagnosticContext | None = None,
    ) -> ConversationResponse:
        return self.process(ConversationInput(message=message, session=session, context=context))

    def process(self, conversation_input: ConversationInput) -> ConversationResponse:
        if not isinstance(conversation_input, ConversationInput):
            raise TypeError("conversation_input must be a ConversationInput")

        command = self.recognize_command(conversation_input.message)
        try:
            if command == ConversationCommand.HELP:
                return self._without_turn(HELP_MESSAGE, conversation_input.session, command)
            if command == ConversationCommand.STATUS:
                return self._status_response(conversation_input.session, command)
            if command == ConversationCommand.CANCEL:
                return self._cancel(conversation_input.session, command)
            if command == ConversationCommand.RESTART:
                return self._restart(conversation_input.session, conversation_input.context, command)
            if command == ConversationCommand.ESCALATE:
                return self._escalate(conversation_input, command)

            if conversation_input.session is None:
                turn = self.session_engine.start_session(
                    conversation_input.message,
                    context=conversation_input.context,
                )
            else:
                turn = self.session_engine.continue_session(
                    conversation_input.session,
                    conversation_input.message,
                    context=conversation_input.context,
                )
            return self._from_turn(turn, command)
        except Exception as exc:  # Conversation boundary returns deterministic error data.
            message = f"Não foi possível processar a conversa: {type(exc).__name__}."
            return self._without_turn(
                message,
                conversation_input.session,
                command,
                errors=(f"{type(exc).__name__}: {exc}",),
            )

    @staticmethod
    def recognize_command(message: str | None) -> ConversationCommand:
        return _COMMANDS.get(normalize_text(message), ConversationCommand.NORMAL)

    def _cancel(
        self,
        session: DiagnosticSession | None,
        command: ConversationCommand,
    ) -> ConversationResponse:
        if session is None:
            return self._without_turn(
                "Não há sessão ativa para cancelar.",
                None,
                command,
                errors=("no active session",),
            )
        return self._from_turn(self.session_engine.cancel_session(session, reason="comando da conversa"), command)

    def _restart(
        self,
        session: DiagnosticSession | None,
        context: DiagnosticContext | None,
        command: ConversationCommand,
    ) -> ConversationResponse:
        if session is None:
            return self._without_turn(
                "Não há sessão ativa para reiniciar.",
                None,
                command,
                errors=("no active session",),
            )

        turn = self.session_engine.start_session(session.original_message, context=context)
        restarted = replace(turn.session, metadata=dict(session.metadata))
        turn = replace(
            turn,
            session=restarted,
            previous_status=session.status,
            current_status=restarted.status,
        )
        return self._from_turn(turn, command)

    def _escalate(
        self,
        conversation_input: ConversationInput,
        command: ConversationCommand,
    ) -> ConversationResponse:
        if conversation_input.session is None:
            return self._without_turn(
                "Não há sessão ativa; descreva o problema para iniciar o atendimento.",
                None,
                command,
                errors=("no active session",),
            )
        turn = self.session_engine.continue_session(
            conversation_input.session,
            conversation_input.message,
            context=conversation_input.context,
        )
        return self._from_turn(turn, command)

    def _status_response(
        self,
        session: DiagnosticSession | None,
        command: ConversationCommand,
    ) -> ConversationResponse:
        if session is None:
            return self._without_turn(
                "Não há sessão de diagnóstico ativa.",
                None,
                command,
                errors=("no active session",),
            )

        top = session.hypotheses[0] if session.hypotheses else None
        hypothesis_id = getattr(top, "incident_id", "nenhuma") if top is not None else "nenhuma"
        confidence = getattr(top, "confidence", 0.0) if top is not None else 0.0
        last_decision = session.decisions[-1].decision_type.value if session.decisions else "nenhuma"
        pending_question = session.current_question or "nenhuma"
        response = (
            f"Status: {session.status.value}; "
            f"interações: {session.interaction_count}; "
            f"hipótese principal: {hypothesis_id}; "
            f"confiança: {confidence:.2f}; "
            f"última decisão: {last_decision}; "
            f"pergunta pendente: {pending_question}."
        )
        return self._without_turn(response, session, command)

    def _from_turn(
        self,
        turn: SessionTurnResult,
        command: ConversationCommand,
    ) -> ConversationResponse:
        decision = turn.workflow_result.decision if turn.workflow_result else None
        if decision is None and turn.session.decisions:
            decision = turn.session.decisions[-1]
        return self._build_response(
            response=turn.response_message,
            session=turn.session,
            workflow_result=turn.workflow_result,
            decision=decision,
            command=command,
            errors=turn.errors,
            state_changed=turn.state_changed,
        )

    def _without_turn(
        self,
        response: str,
        session: DiagnosticSession | None,
        command: ConversationCommand,
        errors: tuple[str, ...] = (),
    ) -> ConversationResponse:
        decision = session.decisions[-1] if session and session.decisions else None
        return self._build_response(
            response=response,
            session=session,
            workflow_result=None,
            decision=decision,
            command=command,
            errors=errors,
            state_changed=False,
        )

    @staticmethod
    def _build_response(
        *,
        response: str,
        session: DiagnosticSession | None,
        workflow_result,
        decision,
        command: ConversationCommand,
        errors: tuple[str, ...],
        state_changed: bool,
    ) -> ConversationResponse:
        status = session.status if session else None
        return ConversationResponse(
            response=response,
            session=session,
            workflow_result=workflow_result,
            decision=decision,
            status=status,
            finished=status in _FINISHED_STATUSES,
            waiting_user=status == DiagnosticSessionStatus.WAITING_USER,
            waiting_confirmation=status == DiagnosticSessionStatus.WAITING_CONFIRMATION,
            metadata={
                "command": command.value,
                "state_changed": state_changed,
                "interaction_count": session.interaction_count if session else 0,
            },
            errors=errors,
        )
