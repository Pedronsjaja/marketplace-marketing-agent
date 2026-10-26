# State and workflow semantics

States: IDENTIFICADO, COLETANDO, VALIDADO, PRONTO_PARA_PUBLICAR, PUBLICADO, LEAD_RECEBIDO, ENCAMINHADO, VENDA, SEM_VENDA, ERRO.

Preparation traverses IDENTIFICADO → COLETANDO → VALIDADO → PRONTO_PARA_PUBLICAR inside one transaction. Intermediate states are code-level transitions; the persisted audit records the completed preparation. Failed validation produces an item error, not a partly published record.

Manual publication moves READY to PUBLICADO with URL and confirmation. Leads, forwarding and outcomes are separate confirmed events. Retry the SAME event with the SAME event_id and payload to avoid double counting. Reusing an ID for different data is rejected.

Counts obey sales + lost <= forwarded <= leads. Sales counts converted leads, not orders, units or revenue. A lead has at most one recorded outcome in this aggregate model. Operators must avoid duplicates across different event IDs; the system cannot recognize two IDs representing the same real interaction.

New leads and incremental outcomes can coexist. For example, a loss followed by a sale is valid if forwarded counts permit it. SEM_VENDA means no sale among recorded outcomes so far; it is not a claim that every lead is closed. VENDA means at least one recorded sale. Status is a workflow marker; use counts to assess pending work.

ERRO and explicit recovery are represented in the core transition graph; the CLI does not expose arbitrary set-state or manual recovery commands.

Observation windows, price/category experiments and causal evaluation require additional records. Do not compare totals from different periods as if exposure and conditions were equal.
