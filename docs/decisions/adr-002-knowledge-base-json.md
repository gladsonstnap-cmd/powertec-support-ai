# ADR-002: Knowledge Base em JSON

- Status: Accepted

## Contexto

O motor precisa de incidentes versionáveis, carregamento local e validação determinística sem acrescentar dependências desnecessárias.

## Decisão

Armazenar a Knowledge Base do Diagnostic Engine em arquivos JSON por domínio, carregados por `KnowledgeLoader` e validados contra os modelos internos.

## Consequências positivas

- formato suportado pela biblioteca padrão;
- revisão simples em Git;
- carregamento determinístico e offline;
- separação dos incidentes por domínio;
- nenhuma nova dependência YAML.

## Consequências negativas

- JSON é mais verboso;
- comentários não são suportados pelo formato;
- alterações exigem validação rigorosa de estrutura e IDs.

## Alternativas consideradas

- YAML: não adotado para evitar nova dependência e variações de parser.
- Banco de dados: adiado porque o pacote atual é local e sem persistência.
- Regras Python embutidas: rejeitadas por misturar conteúdo e implementação.
