# Literature review: MandiSaathi (tasks 1.7 → 8.4)

Status: 19 rows annotated, all citations checked 2026-11-28, comparison table written (task 8.4, D-042);
**open: I must check ≥ 15 rows myself (`Read` → `abstract`/`full`)**. Started 2026-11-23 (task 1.7). Due complete: Day 8 (task 8.4): ≥ 15 annotated papers + comparison
table incl. Namal FYP and Zarai Mandi. Feeds report chapter 2 (task 18.1).

## Search protocol
- Databases: Google Scholar, IEEE Xplore, arXiv, RePEc/IDEAS, ICAR ePubs (Indian agri journals).
- Years: 2015–2026, plus classic method papers of any year.
- Keywords: agricultural price forecasting; mandi price prediction; wholesale vegetable price forecasting
  Pakistan/Punjab; probabilistic forecasting LightGBM; conformal prediction time series; mobile phones
  agricultural markets price dispersion; SMS/WhatsApp market information farmers; cobweb supply response.
- Include: peer-reviewed or well-cited preprint; method or evidence we use or argue against.
  Exclude: blogs, vendor pages (those go in the comparison table, not here).

## Themes and targets (≥ 17 total)
| Theme | Scope | Target | Rows now |
|---|---|---|---|
| T1 | Agricultural price forecasting (mandi / wholesale, South Asia) | ≥ 6 | 6 |
| T2 | Forecasting methods, evaluation, uncertainty | ≥ 4 | 6 |
| T3 | Long-horizon prices, supply response, spatial prices / where to sell | ≥ 3 | 3 |
| T4 | Market information to farmers by phone; farm assistants and voice | ≥ 4 | 4 |

## Annotated table
Read level: `full` = whole paper read by me; `abstract` = abstract/summary checked by me;
`draft` = annotation drafted by Claude from abstracts/indexes, **not yet checked by me** (must become
`abstract` or `full` before the report cites it). Report ref = number in the FYP-I report draft.
Cite check = Claude matched authors, title, venue and volume/pages against the DOI or index page on that date, and the
key result too for rows 7–12, 16, 18, 19 (D-042). It does not change `Read`: only my own check does.

| # | Theme | Citation | Problem & data | Method | Key result | Use in MandiSaathi | Read | Report ref | Cite check (2026-11-28) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | T2 | G. Ke et al., "LightGBM: A highly efficient gradient boosting decision tree," in *Proc. NeurIPS*, 2017. | Fast GBDT on large tabular data | Histogram GBDT with gradient-based one-side sampling (GOSS) and exclusive feature bundling (EFB) | Up to ~20× faster training than standard GBDT at similar accuracy | Our F1 model family (global model across mandi × crop series); quantile objective gives P10/P50/P90 | draft | [4] | NeurIPS 2017 (known venue, not re-fetched) |
| 2 | T2 | S. Makridakis, E. Spiliotis, V. Assimakopoulos, "M5 accuracy competition: Results, findings, and conclusions," *Int. J. Forecasting*, 38(4), 1346–1364, 2022. | 42,840 hierarchical Walmart daily sales series | Competition of ~5,500 teams vs statistical benchmarks | Top entries were mostly LightGBM trained globally across series; beat simple benchmarks clearly | Justifies a global GBDT over per-series ARIMA; also that simple benchmarks must be reported | draft | [5] | doi:10.1016/j.ijforecast.2021.11.013 |
| 3 | T2 | R. J. Hyndman, A. B. Koehler, "Another look at measures of forecast accuracy," *Int. J. Forecasting*, 22(4), 679–688, 2006. | Flaws of MAPE, RMSE across series | Proposes scaled errors (MASE) vs in-sample naive forecast | MASE is scale-free, defined at zeros, < 1 means better than naive | Our headline F1 metric: MASE vs yesterday's price (naive) | draft | [10] | doi:10.1016/j.ijforecast.2006.03.001 |
| 4 | T2 | T. Gneiting, A. E. Raftery, "Strictly proper scoring rules, prediction, and estimation," *J. Amer. Statist. Assoc.*, 102(477), 359–378, 2007. | How to score probabilistic forecasts | Theory of proper scoring rules (CRPS, quantile/pinball score) | Proper rules reward honest forecast distributions; quantile score is proper for quantiles | Pinball loss for P10/P50/P90; interval coverage is checked alongside | draft | [11] | doi:10.1198/016214506000001437 |
| 5 | T2 | A. N. Angelopoulos, S. Bates, "A gentle introduction to conformal prediction and distribution-free uncertainty quantification," arXiv:2107.07511, 2021. | Calibrated prediction sets without model assumptions | Split / conformalized quantile regression | Finite-sample marginal coverage guarantee under exchangeability | Calibrate the 80% price range; note time series break exchangeability (needs rolling calibration) | draft | [6] | arXiv:2107.07511 (not re-fetched) |
| 6 | T2 | S. M. Lundberg, S.-I. Lee, "A unified approach to interpreting model predictions," in *Proc. NeurIPS*, 2017. | Explaining individual predictions | SHAP: Shapley-value feature attributions; TreeSHAP for trees | Unifies LIME/DeepLIFT etc. under additive attributions with consistency guarantees | "Why" line in replies (top driver, rendered by template) and error analysis | draft | [7] | NeurIPS 2017 (known venue, not re-fetched) |
| 7 | T1 | R. K. Paul, M. Yeasin, C. Tamilselvi, A. K. Paul, P. Sharma, P. S. Birthal, "Can deep learning models enhance the accuracy of agricultural price forecasting? Insights from India," *Intell. Syst. Account. Finance Manag.*, 32(1), e70002, 2025. | Monthly wholesale prices, 19 commodities, 143 Indian markets, 2010–2022 | GRU/LSTM/RNN vs random walk w/ drift, ARIMA, ANN, SVR | DL beat ML and stochastic models for many (not all) commodities | Closest large-scale analogue; monthly not daily, no costs or market choice: our gap | draft | — | RePEc wly:isacfm v32 i1 e70002 |
| 8 | T1 | R. K. Paul et al., "Machine learning techniques for forecasting agricultural prices: A case of brinjal in Odisha, India," *PLoS ONE*, 17(7), e0270553, 2022. | Daily wholesale brinjal prices, 17 Odisha markets | GRNN, SVR, RF, GBM vs ARIMA; Diebold-Mariano + model confidence set | GRNN best in all 17 markets; RF tied in 4; ARIMA weaker | Daily mandi-level perishable prices like ours; DM test is a model for our E-tests | draft | — | doi:10.1371/journal.pone.0270553 (PMC9258887) |
| 9 | T1 | A. Rasheed, M. S. Younis, F. Ahmad, J. Qadir, M. Kashif, "District wise price forecasting of wheat in Pakistan using deep learning," arXiv:2103.04781, 2021. | Pakistani district wheat prices with weather, production, consumption | LSTM vs classical ML and statistical models | LSTM reported best | Only Pakistani ML price paper found so far; wheat is government-set-price heavy, unlike vegetables | draft | — | arXiv:2103.04781 (preprint, v1 only) |
| 10 | T1 | L. Menculini, A. Marini, M. Proietti, A. Garinei, A. Bozza, C. Moretti, M. Marconi, "Comparing Prophet and deep learning to ARIMA in forecasting wholesale food prices," *Forecasting*, 3(3), 644–662, 2021. | Sale prices of an Italian food wholesaler | ARIMA vs Prophet vs LSTM vs CNN+LSTM | ARIMA and LSTM similar; CNN+LSTM best overall but slow to tune; Prophet clearly less accurate | Simple models are hard to beat → our naive/seasonal baselines matter | draft | — | doi:10.3390/forecast3030040 |
| 11 | T1 | R. L. Manogna, V. Dharmaji, S. Sarang, "Enhancing agricultural commodity price forecasting with deep learning," *Scientific Reports*, 15, 20903, 2025. | Daily AGMARKNET wholesale prices, 23 commodities (incl. onion, tomato, potato), 165 Indian markets, 2010–2024 | ARIMA, SVR, XGBoost, MLP, RNN, LSTM, GRU, ESN | LSTM/GRU best (abstract: GRU RMSE onion 369.5 vs ARIMA 1564.6); naive/random-walk benchmark not reported | Daily mandi data and our three crops; contrast: no naive baseline, no ranges, no costs | draft | — | doi:10.1038/s41598-025-05103-z (PMC12215695) |
| 12 | T1 | M. Anwar et al. (Punjab Economic Research Institute), "Determinants of potato prices and its forecasting: A case study of Punjab, Pakistan," MPRA Paper 66678, Sep. 2015. | Annual Punjab (Pakistan) potato prices 1998–2014 | Regression on determinants; ARIMA/ARMA forecasts | Temperature and world oil prices significant; support prices matter | Only Punjab-Pakistan potato price study found; annual, so context only (no daily skill claim) | draft | — | MPRA 66678 (mpra.ub.uni-muenchen.de/66678) |
| 13 | T3 | M. Ezekiel, "The cobweb theorem," *Quarterly J. Economics*, 52(2), 255–280, 1938. | Why farm prices cycle | Lagged supply response to last season's price | Planting on last price produces oscillating price cycles | F3 harvest outlook: seasonal climatology benchmark; warns that advice itself can move prices | draft | [9] | doi:10.2307/1881734 |
| 14 | T3 | J. C. Aker, "Information from markets near and far: Mobile phones and agricultural markets in Niger," *AEJ: Applied Economics*, 2(3), 46–59, 2010. | Grain prices across Niger markets, 2001–2006 phone rollout | Difference-in-differences on market pairs | Phones cut grain price dispersion 10–16%, more for distant (high transport cost) pairs | Price gaps between mandis are real and information-sensitive → F2 "where to sell after costs" | draft | — | doi:10.1257/app.2.3.46; **10–16% not confirmed** (abstract not reachable; 2008 working paper says ≥ 6.4% / ~20%): check before citing the figure |
| 15 | T3 | R. Jensen, "The digital provide: Information (technology), market performance, and welfare in the South Indian fisheries sector," *QJE*, 122(3), 879–924, 2007. | Kerala fish markets, phone rollout | Staggered rollout natural experiment | Price dispersion and waste fell sharply; fishermen profits rose | Strongest evidence that where-to-sell information pays; motivates F2 | draft | — | doi:10.1162/qjec.122.3.879 |
| 16 | T4 | M. Fafchamps, B. Minten, "Impact of SMS-based agricultural information on Indian farmers," *World Bank Econ. Rev.*, 26(3), 383–414, 2012. | Maharashtra farmers, RES-RML SMS service | Randomized controlled trial | No significant effect on prices received or crop value | Counter-evidence: price info alone may not help → our cost-aware advice + honest scope of claims | draft | — | doi:10.1093/wber/lhr056 |
| 17 | T4 | A. Radford et al., "Robust speech recognition via large-scale weak supervision," arXiv:2212.04356, 2022. | Multilingual ASR | Whisper: encoder-decoder trained on 680k h weak labels | Strong zero-shot ASR incl. Urdu (higher WER than English) | Urdu voice-note path; WER must be measured on our own clips | draft | [8] | arXiv:2212.04356 (not re-fetched) |
| 18 | T4 | M. Murad, M. Ahmed, N. Ul Din, M. F. Shahid, S. Siddiqui, D. Byers, M. H. Tanveer, R. C. Voicu, "Agentic AI framework to automate traditional farming for smart agriculture," *AgriEngineering*, 8(1), art. 8, 2026. | Farm operations | Multi-agent system: soil, weather and vision (disease) agents + supervisory chatbot | Coordinated, context-aware farm decisions (from citing/index pages; full text not read) | Contrast: agronomy, not prices or where to sell | draft | [12] | doi:10.3390/agriengineering8010008 |
| 19 | T4 | D. J. Samuel Ravindran, I. Skarga-Bandurova, Sivakumar V, M. Awais, Mithra S, "AgroLLM: Connecting farmers and agricultural practices through large language models for enhanced knowledge transfer and practical application," *AgriEngineering*, 8(1), art. 38, 2026. | Farmer knowledge Q&A; corpus of 19 agricultural textbooks; 504-question benchmark | RAG + a domain-knowledge processing layer (DKPL) over Gemini / GPT-4o mini / Mistral | GPT-4o mini + DKPL-constrained RAG best, 95.2% accuracy; fewer hallucinations and numerical errors | Contrast: the LLM still writes the facts; we template every number | draft | [13] | doi:10.3390/agriengineering8010038 |

## Still to find (by Day 8)
- T1: one more Pakistan/Punjab vegetable price paper (try Pakistan J. Agric. Sci., Pakistan J. Agric. Res.,
  query "AMIS" / "Lahore market" / "tomato onion price Pakistan forecasting").
- T3: one paper on farmers' market choice with transport costs (lead: Zanello, Shankar, Srinivasan, AES 2012,
  northern Ghana).
- T4: one study on WhatsApp/voice advisory for farmers in South Asia.

## Comparison table (task 8.4)
Existing Pakistani tools vs MandiSaathi. Sources: Namal FYP project page [3] (via search index, 2026-11-28: the page
itself refused connections); Zarai Mandi and AMIS as described in the report draft from their sites (accessed 17–18 Nov
2026; Zarai Mandi is never fetched by code). "Not stated" = the public page does not say; it does not mean absent.

| System | Channel | Data source | Forecast (horizon, uncertainty) | Where to sell after costs | Harvest outlook | Voice / Urdu | Evaluation reported |
|---|---|---|---|---|---|---|---|
| Namal University FYP [3] (2025) | Streamlit web app | AMIS daily price + quantity, 2021–2025, 8 crops, 10 Punjab cities | Random Forest price prediction; horizon and ranges not stated | Suggests the best city; transport/commission not stated | Not stated | No | No accuracy on the project page |
| Zarai Mandi [1] | Mobile app (login), paid market updates | Own field-verified daily rates (company claim: 150+ markets) | Paid market updates; method and accuracy not published | No (manual comparison of rates) | Not stated | Not stated | None published |
| AMIS Punjab [2] | Website | Government daily mandi price tables (history from 2007) | None | No | No | No voice; site language not checked | n/a |
| **MandiSaathi** | WhatsApp text + Urdu voice notes | FYP-I synthetic (A1, labelled); FYP-II co-supervisor export, AMIS backup | F1: 1–7 days, P10/P50/P90 with 80% conformal range; only for covered series | F2: net after transport, commission, spoilage; P10 risk rule; "nazdeeki mandi theek hai"; assumptions printed | F3: harvest-month range + tercile words; offline in FYP-I, in the bot only where skill > 0 | Roman Urdu / Urdu / English; voice in | Pre-registered S1–S5 (ps_v1, frozen at G2); FYP-I pipeline check on SYN/SYN-NULL; real lockbox opened once in FYP-II |

Gap MandiSaathi fills: none of the three gives a range, costs or a "stay at the nearest mandi" answer, and none reports
an evaluation. Research analogues (rows 7, 8, 11) forecast Indian mandi prices but stop at point accuracy: no costs,
no market choice, no channel to the farmer. Kissan helplines were dropped from the table: no citable public source found.
