# Handoff — próxima sessão

> Estado do trabalho ao limpar o contexto em 2026-05-26. Ler junto com os dois
> documentos de referência abaixo (que têm o conhecimento; este arquivo tem só o
> **estado do processo** e os próximos passos).

## Documentos de referência (já completos)

- `docs/api-quantum.md` — engenharia reversa da API do Quantum (busca, série,
  benchmarks, extrato/carteira, endpoint REST de carteira). Fonte da verdade.
- `docs/superpowers/specs/2026-05-26-refatoracao-backend-fundacao-design.md` —
  design **aprovado** da refatoração do back-end, Fase 1 (fundação).

## Onde paramos (atualizado 2026-05-26, 2ª sessão)

As 3 perguntas em aberto foram **fechadas** e o **plano de implementação** foi
escrito: `docs/superpowers/plans/2026-05-26-refatoracao-backend-fundacao.md`
(11 tasks, TDD, bottom-up).

### Perguntas em aberto — RESOLVIDAS
1. **Colunas promovidas:** mantidas (`cnpj`, `ticker`, `setor`, `gestora`,
   `primeira_cota`, `subtipo`).
2. **Threading:** mantém `threading.Thread` + `Job` (sem Celery).
3. **`PORTFOLIO`:** removido do enum `TipoAtivo` nesta fase.

### Captura adicional desta sessão
Ordens de medidas de `/medidas/valor` capturadas via Playwright e registradas em
`docs/api-quantum.md`: **FI=24, FII=22, ACAO=14**. (Resolveu a lacuna que
impedia parsear metadados de FII/ACAO por posição.)

## Próximos passos

1. **Executar o plano** `docs/superpowers/plans/2026-05-26-refatoracao-backend-fundacao.md`
   (skill `subagent-driven-development` recomendado, ou `executing-plans`).
2. Decidir branch + commit (nada commitado ainda — ver pendência abaixo).

## Pendências técnicas conhecidas

- ⚠️ **Bug latente não corrigido:** `quantum_scrapper.py` →
  `_parsear_resultados_busca` faz `int(item["identificador"])`, que quebra
  (`ValueError`) em resultados `RENDA_FIXA` (id string, ex.: `"VALE38"`). A Fase 1
  resolve isso ao tornar `id_quantum` string; até lá, o bug existe no código atual.
- Nada foi **commitado** nesta sessão (branch `main`, mudanças acumuladas:
  `pyproject.toml`, `uv.lock`, `quantum_scrapper.py` com `buscar_ativos`, e os docs
  novos). Decidir branch + commit na próxima sessão.

## Fases seguintes (fora da Fase 1)

- Composição de carteira investida (REST JSON p/ FI; extrato `.qt` p/ FII).
- Front-end (templates Django) para as novas funcionalidades.
- Cálculo local de métricas de risco a partir da cota diária.
