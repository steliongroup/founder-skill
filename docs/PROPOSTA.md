# Proposta: da "founder-skill" a un valutatore di idee basato su fatti

Data: 2026-10-07. Stato: approvata dall'utente il 2026-10-07 (tutte le decisioni del §10 come proposte). Fase 1 implementata (vedi §9).
Base: analisi della repo attuale e tre ricerche (metodo anti-bias, simulazione dei
consumatori e MiroFish, fonti di dati gratuite). Le fonti sono in fondo.

## 1. Obiettivo

Un metodo il più automatico possibile per valutare molte idee:

- **tipi**: software desktop, tablet o mobile, web app, B2B e B2C, un solo paese o globale;
- **stato**: da idea grezza a idea già ricercata;
- **base**: numeri e fatti verificati, non opinioni;
- **bias**: ridotti sia quelli del fondatore sia quelli dell'AI;
- **risultati confrontabili tra idee diverse**.

Costi: solo l'AI. Claude tramite l'abbonamento, OpenRouter per i lavori pesanti e
ripetitivi, con un tetto di spesa. Nessun SaaS a pagamento.

### Un limite da dire subito

Nessun metodo elimina del tutto i bias, e nessuna simulazione produce fatti. Il
sistema può fare tre cose:

1. separare in modo visibile **fatti verificati**, **dati deboli**, **affermazioni
   del fondatore** e **simulazioni**;
2. partire sempre dai **tassi base** (base rate) del settore invece che
   dall'ottimismo;
3. dire **quale esperimento reale** (landing page, interviste) trasforma un'ipotesi
   in un fatto.

## 2. Cosa non va nella repo attuale (per questo uso)

| Problema | Effetto |
|---|---|
| Modello economico da bar (prezzo × pezzi al giorno, capacità) | Non rappresenta freemium, abbonamenti, churn, CAC |
| 7 skill su 11 sono solo prompt | Risultato simile a un buon prompt diretto |
| Panel = 100 sub-agent Claude | 6-9M token di abbonamento; un solo modello, quindi bias uniforme e ottimismo |
| Van Westendorp su prezzi inventati dall'AI | Precisione apparente |
| Nessuna verifica delle fonti | Numeri e citazioni possono essere allucinati |
| Il valutatore sa che l'idea è "tua" | Rischio di compiacenza (sycophancy) |
| Brand, ops, launch e offer arrivano prima di sapere se l'idea regge | Tempo e token spesi su idee da scartare |

Si tiene: la cartella condivisa per ogni idea, gli script deterministici, il
verdetto calcolato dal codice e non scritto dall'AI.

## 3. Principi del metodo

Ogni principio viene da una pratica con prove a supporto (fonti nel §11).

1. **Pre-registrazione.** Criteri, pesi, soglie di scarto (kill threshold) e
   ancore dei punteggi sono fissati in `rubric.vN.json` **prima** della ricerca.
   Il file ha un hash e non cambia per una singola idea.
2. **Tassi base prima di tutto.** Ogni stima (conversione, churn, CAC, retention)
   parte da una tabella `baserates.json` con fonte, anno, campione e segmento.
   L'AI può spostarla solo con prove citate, e lo spostamento ha un limite
   (massimo un quartile).
3. **Qualità della prova, gradi A-D.**

   | Grado | Cosa comprende |
   |---|---|
   | A | Dati primari o statistiche ufficiali |
   | B | Report di settore con campione noto |
   | C | Blog, aggregatori, fonte singola |
   | D | Affermazione del fondatore o ricordo dell'AI |

   Un numero vale solo se **il codice** ha scaricato la pagina e ritrovato la
   citazione e il numero. Altrimenti scende a D.
4. **Triangolazione.** Un dato chiave è "verificato" solo se lo confermano 2 o più
   fonti indipendenti.
5. **Valutazione alla cieca.** Il giudice vede una scheda neutra ("L'azienda X
   propone…"). Non sa che l'idea è tua né quale preferisci. Gli aggettivi
   entusiasti vengono tolti.
6. **Giuria di più modelli.** Da 3 a 5 giudici di famiglie diverse via
   OpenRouter, ordine delle informazioni invertito.
   - Si usa la mediana.
   - La dispersione tra giudici diventa una misura di incertezza.
   - Ogni voto deve citare gli ID dei fatti; un voto senza citazioni è scartato
     dal codice.
7. **Premortem e red team** affidati ad agenti separati. Usano solo fatti
   verificati e la tassonomia delle cause di fallimento delle startup (CB
   Insights).
8. **Fermi e Monte Carlo.** Ricavi = segmento × raggiungibili × conversione ×
   prezzo × retention. Ogni input è un intervallo; il risultato è P10/P50/P90,
   non un numero solo.
9. **Calibrazione nel tempo.** Le previsioni hanno probabilità esplicite, ad
   esempio P(≥100 clienti paganti in 12 mesi). Si registrano e si confrontano con
   gli esiti reali (punteggio di Brier). Si tengono 5-10 "idee di riferimento"
   con esito noto da rivalutare quando cambiano modelli o prompt.

## 4. Pipeline e skill proposte

Ogni idea vive in `ideas/<id>/`. Tutti i fatti stanno in `evidence.jsonl` con
questi campi: `{id, claim, value, unit, url, quote, date, publisher, grade,
verified, fetched_at}`.

### Fase A: valutazione (per ogni idea)

| # | Skill | Fa | Codice (deterministico) | AI |
|---|---|---|---|---|
| 0 | `/valuta` | Orchestratore: modo `quick` (scrematura) o `full`; riprende da dove si era fermato | stato della pipeline | Claude |
| 1 | `intake` | Dall'idea, o dai documenti che hai già, ricava la **scheda cieca**: archetipo (B2B/B2C, piattaforma, paese), affermazioni del fondatore come ipotesi di grado D | classificazione, rimozione del tono | Claude |
| 2 | `prereg` | Sceglie la rubrica per archetipo e la congela | hash, versione | - |
| 3 | `demand` | Domanda di ricerca: Google Trends (trendspy), autocompletamento di Google, YouTube e Bing, pageview di Wikipedia; Keyword Planner opzionale | script Python, cache | Claude sceglie le parole chiave |
| 4 | `competitors` | Scoperta (HN Algolia, GitHub, iTunes, Google Play, Product Hunt, web) e trazione: recensioni, fascia di installazioni, rank Tranco/CrUX, età del dominio (RDAP), stack tecnologico (webappanalyzer); pagine prezzi con crawl4ai o Playwright | raccolta e normalizzazione | Claude mappa e classifica |
| 5 | `voice` | Problemi dei clienti: recensioni da 1-3 stelle sugli store, HN, Stack Exchange, commenti YouTube, Reddit via ricerca web | verifica delle citazioni | Claude raggruppa i temi |
| 6 | `market` | TAM/SAM/SOM dal basso con dati ufficiali (Eurostat SBS e ICT, US Census CBP, World Bank, ISTAT, OECD) | formula e Monte Carlo | Claude sceglie i codici NACE/NAICS |
| 7 | `panel` | Panel simulato **economico e tarato** (vedi §5) | OpenRouter in parallelo, punteggio SSR, conteggi | modelli economici |
| 8 | `pricing` | Distribuzione dei prezzi dei concorrenti, Van Westendorp dal panel (solo **relativo**), prezzo da testare | script | Claude |
| 9 | `economics` | Unit economics per software: MRR, conversione free→paid, churn, LTV, CAC, payback, mesi alla sostenibilità, P10/P50/P90, partendo dai tassi base | script (sostituisce il modello da bar) | - |
| 10 | `risks` | Premortem, red team, checklist normativa per paese (GDPR, AI Act, consumatori), dipendenza da piattaforme | - | agenti separati |
| 11 | `jury` | Giuria cieca di più modelli sulla rubrica ancorata | validatore delle citazioni, mediana, dispersione | 3-5 modelli via OpenRouter |
| 12 | `verdict` | Punteggio, **confidenza** (copertura di prove A/B, dispersione della giuria), soglie di scarto scattate, rischi principali, "cosa cambierebbe il verdetto", **esperimento reale più economico** con soglia fissata prima | tutto in codice | Claude scrive solo il riassunto |

**Verdetto:** `KILL` / `PIVOT` / `TEST` / `GO`, sempre con la confidenza
(bassa, media, alta) e la percentuale di prove verificate.

### Fase B: trasversali

| Skill | Fa |
|---|---|
| `portfolio` | Classifica tutte le idee con la stessa rubrica; percentile; registro delle previsioni e Brier |
| `validate` | Kit per i test reali: landing page o "fake door", script di intervista secondo il Mom Test, soglia di successo pre-registrata. Registra i risultati reali come prove di grado A e ricalcola il verdetto |

### Fase C: costruzione (solo per le idee con verdetto GO o TEST superato)

`gtm` (posizionamento, canali, campagna), `brand`, `ops`, `launch`. Si
riadattano le skill attuali; non fanno parte della valutazione.

### Due modi d'uso

- **`quick`, per scremare idee grezze**: passi 1, 2, 3 in versione ridotta, 4
  ridotto, 9 con i soli tassi base, 10 senza normativa, 12. Obiettivo: KILL o
  "merita il full" in ~20-30 minuti.
- **`full`**: tutti i passi.
- **Idee già ricercate**: `intake` importa i documenti esistenti, ma ogni loro
  affermazione entra come grado C o D finché non viene verificata. Così le
  ricerche passate servono senza falsare il voto.

## 5. Il panel di consumatori: perché non MiroFish

Che cosa è MiroFish:

- è un motore di previsione dell'opinione pubblica: simula Twitter e Reddit con
  agenti ricavati da persone e organizzazioni citate nei documenti che gli dai;
- usa CAMEL-AI OASIS e, **obbligatoriamente, Zep Cloud** (piano gratuito da 10k
  crediti al mese, poi a pagamento; versioni locali solo in fork non ufficiali);
- consuma circa **5-8M token per simulazione**, quasi tutti in like e
  ricondivisioni simulate;
- **non produce intenzioni d'acquisto strutturate**;
- **non ha studi pubblicati di validazione**.

È adatto a domande del tipo "come reagirebbe il pubblico a un annuncio", non a
"comprerebbero a questo prezzo e perché no". Si può tenere come modulo opzionale
`virality` in futuro.

Le alternative valutate (TinyTroupe, OASIS, genagents) sono più pesanti o
richiedono dati reali che non avremo.

**Proposta: uno script leggero, `panel.py v2`, basato sul metodo con la migliore
validazione pubblicata.**

1. **Persone ancorate a dati reali.** Le persone simulate si costruiscono dalle
   lamentele reali raccolte da `voice` e dai segmenti di `market`, non dalla
   fantasia del modello.
   - Sono stratificate per segmento, reddito o dimensione aziendale, alternativa
     usata oggi e gravità del problema.
   - Per il B2B conta anche chi ha il potere di spesa.
   - Si includono di proposito persone che non comprerebbero.
2. **Risposte libere.** Le risposte sono in testo libero e passano per la
   **Semantic Similarity Rating** (SSR: libreria `pymc-labs/semantic-similarity-rating`
   più embedding locali gratuiti). Chiedere direttamente un numero da 1 a 5 dà
   distribuzioni irrealistiche; con la SSR si arriva a circa il 90% dell'affidabilità
   test-retest umana.
3. **Più modelli economici via OpenRouter**, 2-3 modelli a rotazione, per ridurre
   le stranezze di un singolo modello.
4. **2-3 prezzi**, assegnati a gruppi diversi, per avere una curva di domanda.
5. **Prodotti di riferimento** con trazione nota, valutati nello stesso giro. Il
   risultato si legge **in relativo** ("meglio o peggio del riferimento X"),
   mai come "il 40% comprerebbe".
6. **Costo stimato: 0,5-1,5 USD** per 100 persone × 3 modelli × 3 prezzi, contro
   6-9M token di abbonamento del panel attuale.

Nel verdetto il panel conta come **prova di grado D**. Serve a trovare
obiezioni, segmenti e prezzi da testare, non a dimostrare la domanda.

## 6. Fonti di dati gratuite scelte

| Area | Strumento | Note |
|---|---|---|
| Domanda | trendspy, autocompletamento, Wikipedia pageviews, YouTube Data API | Trends dà valori relativi; YouTube ha 10k unità al giorno gratis con chiave |
| Volumi assoluti | Google Keyword Planner | Opzionale: account Ads gratuito; dall'interfaccia vedi fasce di volume; l'API richiede una carta registrata (nessuna spesa) |
| Concorrenti | HN Algolia, GitHub API, iTunes Search e RSS delle recensioni, google-play-scraper, Product Hunt (uso personale) | Gli scraper possono rompersi: versioni bloccate e cache |
| Trazione | Tranco, CrUX, RDAP, webappanalyzer, Common Crawl | Sostituiscono SimilarWeb e BuiltWith, con meno precisione |
| Prezzi | crawl4ai o Playwright, Wayback CDX | Prezzi con data e fonte |
| Mercato | Eurostat, US Census CBP, World Bank, ISTAT, OECD, SEC EDGAR | Nessuna chiave o chiave gratuita |
| Software esistente | idea-reality-mcp | Solo per idee di software e strumenti per sviluppatori |

**Scartati:**

- open-seo e open-seo-mcp-skills: richiedono DataForSEO (deposito minimo di 50 USD)
  o un connettore a pagamento;
- Crunchbase (a pagamento);
- G2 e Capterra (protezione anti-bot);
- Reddit via API: chiusa dal 2026; si usa la ricerca web `site:reddit.com`.

Per le API REST semplici si usano piccoli script Python con cache invece di
molti server MCP: sono più stabili e consumano meno contesto.

## 7. Cosa fai tu e cosa fa l'AI

| Tu | AI e codice |
|---|---|
| Scrivi l'idea in poche righe o indichi i documenti esistenti (5-10 minuti) | Tutto il resto, dalla scheda cieca al verdetto |
| Approvi una volta la rubrica e i pesi, non per ogni idea | Raccolta dati, verifica delle fonti, calcoli, giuria |
| Leggi il verdetto (circa 10 minuti) | Propone l'esperimento reale e la sua soglia |
| Fai l'esperimento reale (landing page, interviste) e ne inserisci i risultati | Ricalcola il verdetto con le prove di grado A |

Le chiavi gratuite opzionali (token GitHub, chiave YouTube, Product Hunt) si
configurano una volta sola.

## 8. Stima dei costi per idea (da misurare dopo l'implementazione)

| Modo | Token dell'abbonamento Claude | OpenRouter | Tempo dell'AI | Tempo tuo |
|---|---|---|---|---|
| `quick` | ~1-3M | ~0,05-0,2 USD (mini-giuria) | 20-30 min | ~15 min |
| `full` | ~6-12M | ~1-3 USD (panel e giuria) | 1-2 ore | ~30 min più l'esperimento reale |

Il tetto di spesa OpenRouter per idea si imposta in `config.json`. Gli script si
fermano prima di superarlo.

## 9. Piano di implementazione

1. **Fondamenta** (fatta il 2026-10-07: `skills/idea-lib/` e le skill `idea-valuta`,
   `idea-intake`, `idea-evidence`, `idea-economics`, `idea-verdict`; in questa
   fase il giudice è un solo sub-agente Claude e `--full` è una ricerca web più
   ampia con lo stesso protocollo):
   - schema di `evidence.jsonl` e verificatore delle fonti;
   - `baserates.json` con fonti;
   - rubriche per archetipo;
   - `intake`, `prereg`, `economics`, `verdict`;
   - test;
   - modo `quick` funzionante solo con i tassi base.
2. **Raccoglitori di dati**: `demand`, `competitors`, `voice`, `market`, con cache
   e degradazione controllata (se una fonte non risponde, il verdetto lo dice).
3. **Lavori su OpenRouter**: `panel` v2 con SSR, `jury` multi-modello, tetto di
   costo, registro delle chiamate.
4. **Trasversali**: `portfolio` (classifica e Brier), `validate` (kit landing page e
   Mom Test), idee di riferimento per la calibrazione.
5. **Fase C**: si riadattano gtm, brand, ops, launch.

Ogni fase è utilizzabile da sola. La prova di ogni fase è far girare il sistema
su un'idea reale (ad esempio Mentore) e su 2-3 idee di riferimento con esito
noto.

**Nota tecnica.** I raccoglitori si devono eseguire sul tuo PC, perché la sessione
cloud blocca molti siti esterni. Qui si scrivono e si testano con dati registrati.

## 10. Decisioni da prendere

1. **Lingua.** Proposta: prompt delle skill in inglese (rendono meglio con tutti
   i modelli), report in italiano.
2. **Nome e repo.** Proposta: continuare in questa repo (`steliongroup/founder-skill`),
   con il nuovo pacchetto accanto alle 11 skill attuali, che verranno poi
   riadattate o rimosse.
3. **OpenRouter.** Hai una chiave? Proposta di tetto: 3 USD per idea in `full`.
4. **Account gratuiti opzionali.** Per un Google Ads con carta registrata (solo
   per i volumi di ricerca, nessuna spesa) proposta: opzionale e spento di
   default.
5. **Dove stanno le idee.** Proposta: un'unica cartella `ideas/`, in una repo
   privata separata, per avere la classifica tra idee.

## 11. Fonti principali

- **Bias e previsioni**
  - Flyvbjerg 2006 (reference class forecasting).
  - Klein 2007 (premortem).
  - Mellers et al. 2014, Tetlock (superforecasting).
  - GRADE (qualità delle prove).
  - Schoenegger et al. 2024 (folla di LLM ≈ folla umana).
  - Verga et al. 2024 (giuria di più modelli).
  - Sharma et al. 2024 (sycophancy).
  - Zheng et al. 2023 (bias dei giudici LLM).
  - Xiong et al. 2024 (eccesso di sicurezza).
- **Tassi base**
  - BLS BED 2024 (sopravvivenza delle imprese).
  - CB Insights (cause di fallimento).
  - Unbounce (conversione delle landing page, SaaS mediana 3,8%).
  - Lenny/OpenView (free→paid 3-5%).
  - RevenueCat 2025 (app in abbonamento: installazione→pagamento 1,9% mediana).
  - AppsFlyer 2025 (retention giorno 30: ~4-6%).
  - ChartMogul 2023 (churn per fascia di ARPA).
  - Benchmarkit 2026 (CAC payback, mediana 16 mesi).
- **Simulazione dei consumatori**
  - Brand, Israeli & Ngwe (HBS 23-062).
  - Argyle et al. 2023.
  - Bisbee et al. 2024 (varianza troppo bassa).
  - Park et al. 2024 (1.000 persone).
  - Toubia et al. 2025 ("Funhouse Mirrors", r≈0,20 sugli individui).
  - Maier et al. 2025 (SSR).
- **Strumenti**
  - github.com/666ghj/MiroFish
  - github.com/microsoft/TinyTroupe
  - github.com/pymc-labs/semantic-similarity-rating
  - github.com/unclecode/crawl4ai
  - github.com/mnemox-ai/idea-reality-mcp
  - pypi trendspy
  - github.com/every-app/open-seo (richiede DataForSEO)

Le cifre dei tassi base sono riportate dalle ricerche e vanno riverificate sulla
fonte quando si compila `baserates.json`; ogni voce avrà URL, anno e campione.
