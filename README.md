# Codex Pulse v3 — monitor flutuante de tokens e prompts para Codex

Aplicação local com código-fonte incluído, em **Python + Tkinter**, para acompanhar consumo de tokens do Codex por chamada, prompt e sessão. Inclui **janela nativa sempre no topo** e dashboard web. Não exige chave de API, conta adicional nem dependências `pip`.

## Começar em 30 segundos

1. Extraia o ZIP em uma pasta do computador **onde o Codex é executado**.
2. **Windows:** execute `iniciar-flutuante-windows.bat` (o Python instalado precisa fornecer Tkinter). **macOS/Linux:** execute `./iniciar-flutuante-macos-linux.sh`. Se preferir: `python3 overlay.py`.
3. A janela aparece no canto superior direito. Arraste pelo cabeçalho para reposicioná-la.
4. Para testar com **dados fictícios**, execute `python3 overlay.py --demo` (Windows: `py overlay.py --demo`).

**Requisitos:** Python 3.10+ e Tkinter. No Linux, pode ser necessário instalar `python3-tk` pelo gerenciador de pacotes. Para verificar: `python3 -m tkinter` (no Windows, `py -m tkinter`).

### Modos e controles

| Ação | Como fazer |
|---|---|
| Sempre no topo | Botão com círculo verde no canto superior direito |
| Alternar **Completo → Compacto → Barra** | Botão `−` / `▱` / `+` ou tecla `Esc` quando o widget tem foco |
| Arrastar | Clique e arraste o cabeçalho |
| **Hoje / Última hora / Sessão mais recente** | Botões no painel completo; no compacto, toque em `FAIXA` |
| Atalhos dos períodos | `Ctrl+1` / `Ctrl+2` / `Ctrl+3` |
| Mostrar/ocultar texto do último prompt | Botão de privacidade do cartão `ÚLTIMO PROMPT` (oculto por padrão) |
| Alerta de custo equivalente | Botão `!` do rodapé; `0` desativa |
| Ajustar transparência | Botões `−` / `+` do rodapé (72% a 100%) |
| Análise detalhada | `Dashboard completo ↗` |
| Fechar | `×` ou `Ctrl+W` |

Preferências são salvas em `~/.codex-pulse/overlay.json`: posição, tamanho, período, opacidade, sempre no topo e limiar de alerta. A opção para **revelar o prompt não é persistida**.

## O que há de novo na versão 3

- **Três tamanhos:** completo com visualização por período, compacto com custo/tokens/chamadas, barra mínima sobre o editor.
- **Filtro útil ao desenvolver:** consumo de **hoje**, dos **últimos 60 minutos** ou da **sessão da última chamada**.
- **Mini-histograma** com tokens consumidos ao longo do período selecionado.
- **Alertas visuais, não intrusivos:** limite configurável de custo equivalente ou uso de janela acima de 80% **somente quando o snapshot é recente**. Nenhuma notificação do sistema ou cobrança é criada.
- **Integridade dos indicadores:** a interface marca valores parciais (`*`), preços ausentes, snapshots desatualizados e janelas de limite já expiradas. Exibe o tempo desde a última chamada.
- **Desempenho melhorado no parser:** evita rescans redundantes e indexa prompts por sessão para vinculação mais eficiente.
- Atualização em segundo plano **a cada 6 segundos**, sem travar a janela enquanto os arquivos são lidos. Leitura exclusivamente local, somente leitura dos logs Codex.

### Sobre o custo exibido

**US$ na interface = quanto os tokens custariam usando os preços informados em `pricing.json` numa hipótese semelhante à API. Não é cobrança do Codex autenticado pelo ChatGPT.** Os preços são configuráveis, por modelo, e podem não refletir a modalidade efetivamente usada. Não são consideradas taxas de ferramentas e outras tarifas especiais. Um modelo sem tarifa não recebe valor inventado; totais parciais mostram `*`.

Alerta de custo: o limiar padrão é **US$ 0,50 equivalente estimado no período selecionado**, configurável no botão `!`. É um indicador informativo, não um limite de gastos aplicado ao Codex.

O **limite de uso** é lido do último evento JSONL gravado pelo Codex. Não há consulta direta à conta OpenAI: pode estar antigo e não representa a cota exata restante. Se já passou o horário de reset informado, exibimos `Registro expirado` em vez de apresentar a antiga porcentagem como atual.

### Histórico / origem dos dados

- `~/.codex/sessions/**/rollout-*.jsonl`
- `~/.codex/archived_sessions/**/rollout-*.jsonl`
- Direcionamento personalizado: `python3 overlay.py --codex-home /caminho/para/.codex`
- Variável `CODEX_HOME` também é respeitada.

Os formatos são legados `event_msg`/`token_count` e mais novos `token_usage_record`. Registros de resposta têm identificação própria e são deduplicados mesmo se arquivos ativos e arquivados contêm cópias. A contabilidade agrupa por prompt usando `turn_id` quando disponível; caso contrário usa o último prompt anterior da sessão. **É uma atribuição aproximada**: subagentes, compaction e versões do Codex com telemetria diferente podem gerar inconsistências. Dados não registrados localmente nunca são inventados.

## Dashboard completo

O dashboard web continua disponível, com histórico por chamada, sessão, modelo e prompt, filtros de pesquisa, uso de cache, tendências e exportação CSV.

- **Windows:** `iniciar-windows.bat`
- **macOS/Linux:** `./iniciar-macos-linux.sh`
- Ou: `python3 codex_pulse.py`
- Abra `http://127.0.0.1:4327`.
- Para testar: `python3 codex_pulse.py --demo`.
- Dados JSON somente em `http://127.0.0.1:4327/api/data`.
- CSV sem prompt: `http://127.0.0.1:4327/api/export.csv`.
- CSV incluindo o texto dos prompts (uso consciente): `http://127.0.0.1:4327/api/export.csv?prompts=1`.

O servidor HTTP escuta apenas **127.0.0.1**. A aplicação não transmite os logs a terceiros, não acessa `auth.json` e não requer chave API. O endpoint local `/api/data` inclui trechos de prompts: evite expô-lo em túneis, proxies ou redes públicas. Não há coleta de telemetria do próprio Codex Pulse.

## Testes e problemas frequentes

```bash
python3 -m unittest discover -s tests -v
```

Se o widget não abrir, tente `python3 overlay.py` no terminal, para ver a mensagem de erro. No macOS, janelas sobre aplicativos em tela cheia e Spaces podem obedecer restrições do próprio sistema; em Windows, tela cheia exclusiva também pode impedir sobreposição. O modo demonstrativo exibe números **fictícios** e não deve ser usado para avaliar custos pessoais.

## Referências

- [OpenAI Codex — repositório oficial](https://github.com/openai/codex)
- [Documentação de preços da API](https://developers.openai.com/api/docs/pricing)
- [codex-monitor](https://github.com/falyx6851-byte/codex-monitor)
- [codex-usage-monitor](https://github.com/harveyxiacn/codex-usage-monitor)
- [tokenreceipt](https://github.com/henrikdukefoss/tokenreceipt)

Projeto independente; nenhum código de terceiros foi incorporado. Licenças/atribuições de eventuais modificações futuras devem ser verificadas antes de publicar o repositório.
# Atualizações automáticas

As distribuições extraídas do pacote `codex-pulse-update.zip` consultam a última
Release estável de `EzekLobo/codex-pulse` ao abrir a janela ou o dashboard.
Uma versão mais nova é instalada automaticamente antes de iniciar a interface.
É necessário Python com Tkinter e permissão de escrita na pasta da aplicação.
Preferências em `~/.codex-pulse` e logs do Codex são preservados.

O atualizador exige o digest SHA-256 do asset informado pelo GitHub, rejeita
pacotes incompletos e caminhos inesperados e restaura os arquivos anteriores
quando uma substituição falha. Sem rede, continua na versão instalada.
A verificação pode acrescentar alguns segundos à inicialização. Não ocorre
atualização durante uma sessão aberta. Não execute várias instâncias na mesma pasta.
Uma interrupção do sistema durante a substituição pode exigir reextrair o pacote.

Checkouts com `.git` não são atualizados automaticamente. Para desativar em uma
distribuição, defina `CODEX_PULSE_AUTO_UPDATE=0`.

Para publicar: atualize `VERSION`, faça commit e envie uma tag correspondente,
como `v3.1.0`. O workflow de release executa os testes, gera o pacote e publica
o asset. As atualizações só estarão disponíveis depois que o código e a tag
forem enviados ao GitHub. Não inclua chaves nem logs no pacote.

