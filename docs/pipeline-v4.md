# Pipeline operacional V4

A V4 acrescenta filas independentes para Facebook e OLX ao framework existente. Reutiliza a validação de produto e a escrita JSON atômica. O fluxo legado continua disponível. A CLI não acessa contas nem publica externamente: modos de publicação descrevem a operação pretendida e os gates de um futuro adaptador.

## Executar

```text
python scripts/marketplace.py v4 plan
python scripts/marketplace.py v4 prepare
python scripts/marketplace.py v4 feedback --input observation.json --confirmed
```

Use `--workspace` antes de `v4` e `--settings`/`--catalog` depois do subcomando para arquivos locais. O exemplo é inteiramente fictício e não possui fotos. Portanto, demonstra os bloqueios sem fabricar anúncios prontos. As evidências de preço também expiram: atualize somente com confirmação real da fonte.

## Parâmetros centrais

`config/pipeline.v4.example.json` concentra meta mínima 10, preferida 15, reserva 5, mínimo Facebook 5 fotos e OLX 1, modos, CEP, entrega, validade do preço e do inventário. Não há meta por tentativas ou por pastas criadas.

Cada plataforma pode selecionar até 15 principais e 5 reservas válidas; os totais LIVE do dia são separados e somados. Reservas passam pelos mesmos gates. Categorias diversas e ausência de submissão anterior melhoram o ranking. Risco LOW/MEDIUM/HIGH é uma heurística sobre o histórico fornecido; ausência de registro não prova ausência de anúncio real.

Limites máximos da OLX precisam de confirmação no formulário da conta: ficam `null` no exemplo público. Uma observação válida para uma conta não vira limite universal. CEP operacional fica em um único campo local; ausente implica `OLX_CEP_REQUIRED`. A cidade operacional não autoriza anunciar retirada em um endereço.

Entrega nacional e frete grátis regional são condições distintas. O texto de entrega só é incluído com `delivery_scope_confirmed=true`. Nunca gerar preço de frete, prazo nacional, transportadora ou frete grátis nacional sem fonte. A frase padrão é “Consulte condições de entrega para sua região.”.

## Identidade, fatos e fotos

Existe um produto canônico com projeções por plataforma. IDs/URLs repetidos são bloqueados. O preço decimal confirmado, a fonte, a identidade e a revisão factual são obrigatórios. Se houver `attributes`, somente valores com `status=CONFIRMED` entram no anúncio; `CONFLICTING`, `PROMOTIONAL`, `TRUNCATED` e `UNSUPPORTED` são omitidos. Atributos secundários ausentes não bloqueiam por si só.

Cada foto deve registrar `path`, `sha256`, `product_source_url`, `ownership_evidence` e `visual_review_confirmed=true`. O arquivo local precisa corresponder ao hash; `product_source_url` precisa corresponder ao produto. Isso valida a integridade e a afirmação documentada do operador, não constitui verificação independente da página pela CLI. Não inferir propriedade pelo nome do arquivo nem completar quantidade com fotos de outro modelo. Fotos repetidas por hash dentro do produto contam uma vez.

Pacotes são escritos em `workspace/v4/POSTS_PRONTOS/<execução>/FACEBOOK`, `OLX` e `RESERVAS/<plataforma>`, com anúncio, dados, fontes, validação e imagens intactas. Facebook recebe identificações. Cada plataforma possui `TODOS_OS_POSTS.txt`. `current-batch.json` só avança depois de concluir a cópia e conferir os hashes; execução incompleta não vira fila atual.

## Feedback e estados

Estados: `READY_TO_POST`, `SUBMITTED`, `LIVE`, `REJECTED_DUPLICATE`, `REJECTED_OTHER`, `NEEDS_REVIEW`, `SOLD`, `ARCHIVED`. `platform_status` permite registrar bloqueios de revisão e ciclo de vida. O comando V4 lê os registros confirmados do `Store` legado e bloqueia sua repetição no alvo configurado em `legacy_platform` (Facebook no exemplo) com `NEEDS_REVIEW`, sem somá-los ao LIVE atual nem propagá-los ao outro canal. `upload_gate` também interrompe novos envios quando a soma LIVE do dia atinge a meta preferida.

`workspace/v4/platform-feedback.json` preserva eventos confirmados. Um evento contém:

```json
{
  "event_id": "DEMO-OBS-001",
  "product_id": "DEMO-V4-001",
  "platform": "FACEBOOK",
  "source_url": "https://example.com/catalog/demo-v4-001",
  "title": null,
  "price": null,
  "submitted_at": null,
  "result": "REJECTED_DUPLICATE",
  "platform_reason": "Exemplo fictício de retorno de duplicidade.",
  "live_confirmed": false,
  "retry_count": 0,
  "evidence": "FICTIONAL"
}
```

Resultados permitidos: `LIVE`, `REJECTED_DUPLICATE`, `REJECTED_OTHER`, `UNKNOWN`. Datas e artefatos desconhecidos ficam `null`. `UNKNOWN` vira `SUBMITTED`, nunca LIVE. `LIVE` exige confirmação explícita e evidência. O contador diário utiliza a confirmação LIVE (ou submissão quando fornecida), no deslocamento UTC configurado; submissões e rejeições não contam. O mesmo produto em plataformas diferentes é contabilizado separadamente. Duplicar um ID de evento é idempotente; alterar seu conteúdo causa erro, sem sobrescrever o evento anterior.

`REJECTED_DUPLICATE → DUPLICATE_QUARANTINE → REPLACE_PRODUCT` vale no alvo que rejeitou. Rejeição Facebook não bloqueia OLX. Se a própria OLX rejeitar, registre quarentena OLX. Uma submissão pendente não volta automaticamente para a fila. Nenhum retry automático, manipulação de pixels, Unicode, fotos ou contas para contornar moderação.

## Publicação assistida e evidência da plataforma

Modos: `PREPARE_ONLY`, `ASSISTED_POSTING` (inicial), `AUTO_POST_WHERE_SUPPORTED`. A última opção retorna `SUPPORTED_ADAPTER_REQUIRED`: configurar o modo não implementa integração externa. Ações externas continuam fora da CLI e exigem autorização pertinente. Não aceitar contratos, adquirir destaques, criar contas ou contratar serviços apenas porque uma tela os oferece.

Antes do preenchimento: `upload_gate` exige inventário autenticado, completo, da plataforma correta e recente; bloqueia produtos já encontrados. `blocking_issue` no inventário produz `HUMAN_ACTION_REQUIRED`. Login, CAPTCHA, 2FA, telefone, limite, anti-spam, bloqueio ou moderação interrompem o envio; não contornar nem insistir.

O preenchimento automático da plataforma não é fonte de verdade. Conferir categoria, marca, lugares, medidas, condição, CEP e descrição contra a fonte aprovada. Corrigir fatos comprovados e omitir os demais; se a UI impedir a omissão, usar `NEEDS_REVIEW`.

Não presumir que a última tela de ofertas é a publicação. Alguns fluxos podem criar/ativar o anúncio antes de oferecer serviços opcionais. Após a submissão, conferir “Meus anúncios”, o status e o link, inclusive pendentes/inativos e notificações. Não repetir um produto por não ter clicado numa tela posterior. Não contar rascunho ou ID interno como LIVE. O adaptador futuro deverá revalidar os gates imediatamente antes de cada envio.

## Pneus e mensagens

Sem fonte de pneus: `TIRE_CATALOG_SOURCE_MISSING`. Um produto `kind=TIRE` requer marca, modelo, medida, largura, perfil, aro, índices de carga/velocidade, condição, preço e fotos confirmados. A CLI não inventa nem pesquisa pneus automaticamente.

`INBOX_FACEBOOK` e `INBOX_OLX` permanecem `EXTERNAL_REVIEW_REQUIRED`: este módulo não lê nem responde mensagens. Integração futura pode registrar `UNREAD`, `PENDING_REPLY`, `RESPONDED`, `FOLLOW_UP` com evidência e autorização apropriadas.

## Validação e limites

```text
python -m unittest discover -s tests -v
python scripts/validation/audit_public.py
```

Testes determinísticos cobrem estados, plataformas independentes, preços, fotos, reservas, cópia, gates, idempotência e rollback. Eles não validam uma integração com OLX/Facebook nem provam publicação real. Nenhum catálogo operacional, anúncio, foto, contato, caminho pessoal, credencial ou sessão privada integra este repositório.
