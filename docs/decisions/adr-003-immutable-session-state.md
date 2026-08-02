# ADR-003: Estado de sessão imutável e sem estado global

- Status: Accepted

## Contexto

O diagnóstico precisa continuar entre mensagens sem mutações invisíveis, listas compartilhadas ou dependência de armazenamento nesta etapa.

## Decisão

Representar cada estado como um `DiagnosticSession` congelado. Cada operação recebe um snapshot e retorna outro; históricos usam tuplas e cópias defensivas. O Session Engine não mantém registro global de sessões.

## Consequências positivas

- estado anterior preservado;
- testes e comparação de transições simplificados;
- menor risco de vazamento entre sessões;
- persistência futura pode armazenar snapshots explícitos.

## Consequências negativas

- cópias têm custo de memória e CPU;
- o chamador é responsável por manter o snapshot atual;
- não há recuperação após reinício do processo.

## Alternativas consideradas

- dicionário global no engine: rejeitado por concorrência e acoplamento.
- mutação da mesma sessão: rejeitada por dificultar auditoria e testes.
- persistência imediata em banco ou Redis: adiada para escopo próprio.
