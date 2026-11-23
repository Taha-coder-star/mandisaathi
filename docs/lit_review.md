# Literature review: MandiSaathi (tasks 1.7 → 8.4)

Status: **started** 2026-11-23 (task 1.7). Due complete: Day 8 (task 8.4): ≥ 15 annotated papers + comparison
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
| T1 | Agricultural price forecasting (mandi / wholesale, South Asia) | ≥ 6 | 6 candidates |
| T2 | Forecasting methods, evaluation, uncertainty | ≥ 4 | 6 |
| T3 | Long-horizon prices, supply response, spatial prices / where to sell | ≥ 3 | 3 |
| T4 | Market information to farmers by phone; farm assistants and voice | ≥ 4 | 4 |

## Annotated table
Read level: `full` = whole paper read by me; `abstract` = abstract/summary checked by me;
`draft` = annotation drafted by Claude from abstracts/indexes, **not yet checked by me** (must become
`abstract` or `full` before the report cites it). Report ref = number in the FYP-I report draft.

| # | Theme | Citation | Problem & data | Method | Key result | Use in MandiSaathi | Read | Report ref |
|---|---|---|---|---|---|---|---|---|
| 1 | T2 | G. Ke et al., "LightGBM: A highly efficient gradient boosting decision tree," in *Proc. NeurIPS*, 2017. | Fast GBDT on large tabular data | Histogram GBDT with gradient-based one-side sampling (GOSS) and exclusive feature bundling (EFB) | Up to ~20× faster training than standard GBDT at similar accuracy | Our F1 model family (global model across mandi × crop series); quantile objective gives P10/P50/P90 | draft | [4] |
| 2 | T2 | S. Makridakis, E. Spiliotis, V. Assimakopoulos, "M5 accuracy competition: Results, findings, and conclusions," *Int. J. Forecasting*, 38(4), 1346–1364, 2022. | 42,840 hierarchical Walmart daily sales series | Competition of ~5,500 teams vs statistical benchmarks | Top entries were mostly LightGBM trained globally across series; beat simple benchmarks clearly | Justifies a global GBDT over per-series ARIMA; also that simple benchmarks must be reported | draft | [5] |
| 3 | T2 | R. J. Hyndman, A. B. Koehler, "Another look at measures of forecast accuracy," *Int. J. Forecasting*, 22(4), 679–688, 2006. | Flaws of MAPE, RMSE across series | Proposes scaled errors (MASE) vs in-sample naive forecast | MASE is scale-free, defined at zeros, < 1 means better than naive | Our headline F1 metric: MASE vs yesterday's price (naive) | draft | [10] |
| 4 | T2 | T. Gneiting, A. E. Raftery, "Strictly proper scoring rules, prediction, and estimation," *J. Amer. Statist. Assoc.*, 102(477), 359–378, 2007. | How to score probabilistic forecasts | Theory of proper scoring rules (CRPS, quantile/pinball score) | Proper rules reward honest forecast distributions; quantile score is proper for quantiles | Pinball loss for P10/P50/P90; interval coverage is checked alongside | draft | [11] |
| 5 | T2 | A. N. Angelopoulos, S. Bates, "A gentle introduction to conformal prediction and distribution-free uncertainty quantification," arXiv:2107.07511, 2021. | Calibrated prediction sets without model assumptions | Split / conformalized quantile regression | Finite-sample marginal coverage guarantee under exchangeability | Calibrate the 80% price range; note time series break exchangeability (needs rolling calibration) | draft | [6] |
| 6 | T2 | S. M. Lundberg, S.-I. Lee, "A unified approach to interpreting model predictions," in *Proc. NeurIPS*, 2017. | Explaining individual predictions | SHAP: Shapley-value feature attributions; TreeSHAP for trees | Unifies LIME/DeepLIFT etc. under additive attributions with consistency guarantees | "Why" line in replies (top driver, rendered by template) and error analysis | draft | [7] |
| 7 | T1 | R. K. Paul, M. Yeasin, C. Tamilselvi, A. K. Paul, P. Sharma, P. S. Birthal, "Can deep learning models enhance the accuracy of agricultural price forecasting? Insights from India," *Intell. Syst. Account. Finance Manag.*, 32(1), e70002, 2025. | Monthly wholesale prices, 19 commodities, 143 Indian markets, 2010–2022 | GRU/LSTM/RNN vs random walk w/ drift, ARIMA, ANN, SVR | DL beat ML and stochastic models for many (not all) commodities | Closest large-scale analogue; monthly not daily, no costs or market choice: our gap | draft | — |
| 8 | T1 | R. K. Paul et al., "Machine learning techniques for forecasting agricultural prices: A case of brinjal in Odisha, India," *PLoS ONE*, 17(7), e0270553, 2022. | Daily wholesale brinjal prices, 17 Odisha markets | GRNN, SVR, RF, GBM vs ARIMA; Diebold-Mariano + model confidence set | GRNN best in all 17 markets; RF tied in 4; ARIMA weaker | Daily mandi-level perishable prices like ours; DM test is a model for our E-tests | draft | — |
| 9 | T1 | A. Rasheed, M. S. Younis, F. Ahmad, J. Qadir, M. Kashif, "District wise price forecasting of wheat in Pakistan using deep learning," arXiv:2103.04781, 2021. | Pakistani district wheat prices with weather, production, consumption | LSTM vs classical ML and statistical models | LSTM reported best | Only Pakistani ML price paper found so far; wheat is government-set-price heavy, unlike vegetables | draft | — |
| 10 | T1 | L. Menculini et al., "Comparing Prophet and deep learning to ARIMA in forecasting wholesale food prices," *Forecasting*, 3(3), 2021 (arXiv:2107.12770). | Italian wholesale food prices | ARIMA vs Prophet vs LSTM/CNN | Check: claims ARIMA competitive with DL on these series | Evidence that simple models are hard to beat → our naive/seasonal baselines matter | draft (verify vol/pages) | — |
| 11 | T1 | Manogna R. L. et al., *Scientific Reports*, 2025, doi:10.1038/s41598-025-05103-z ("Enhancing agricultural commodity price forecasting with deep learning"). | Daily Indian commodity prices | ARIMA, SVR, XGBoost, MLP, LSTM, GRU, ESN | Check | Daily benchmark set close to ours | candidate: verify authors + result | — |
| 12 | T1 | Punjab Economic Research Institute, potato price determinants and ARIMA forecasts, MPRA paper 66678. | Punjab (Pakistan) potato prices | ARIMA / ARMA | Check | Pakistani Punjab, same crop family as our demo | candidate: verify authors, year | — |
| 13 | T3 | M. Ezekiel, "The cobweb theorem," *Quarterly J. Economics*, 52(2), 255–280, 1938. | Why farm prices cycle | Lagged supply response to last season's price | Planting on last price produces oscillating price cycles | F3 harvest outlook: seasonal climatology benchmark; warns that advice itself can move prices | draft | [9] |
| 14 | T3 | J. C. Aker, "Information from markets near and far: Mobile phones and agricultural markets in Niger," *AEJ: Applied Economics*, 2(3), 46–59, 2010. | Grain prices across Niger markets, 2001–2006 phone rollout | Difference-in-differences on market pairs | Phones cut grain price dispersion 10–16%, more for distant (high transport cost) pairs | Price gaps between mandis are real and information-sensitive → F2 "where to sell after costs" | draft | — |
| 15 | T3 | R. Jensen, "The digital provide: Information (technology), market performance, and welfare in the South Indian fisheries sector," *QJE*, 122(3), 879–924, 2007. | Kerala fish markets, phone rollout | Staggered rollout natural experiment | Price dispersion and waste fell sharply; fishermen profits rose | Strongest evidence that where-to-sell information pays; motivates F2 | draft | — |
| 16 | T4 | M. Fafchamps, B. Minten, "Impact of SMS-based agricultural information on Indian farmers," *World Bank Econ. Rev.*, 26(3), 383–414, 2012. | Maharashtra farmers, RES-RML SMS service | Randomized controlled trial | No significant effect on prices received or crop value | Counter-evidence: price info alone may not help → our cost-aware advice + honest scope of claims | draft | — |
| 17 | T4 | A. Radford et al., "Robust speech recognition via large-scale weak supervision," arXiv:2212.04356, 2022. | Multilingual ASR | Whisper: encoder-decoder trained on 680k h weak labels | Strong zero-shot ASR incl. Urdu (higher WER than English) | Urdu voice-note path; WER must be measured on our own clips | draft | [8] |
| 18 | T4 | M. Murad et al., "Agentic AI framework to automate traditional farming for smart agriculture," *AgriEngineering*, 8(1), art. 8, 2026. | Farm automation | Agentic AI | Check | Contrast: agronomy-focused, not prices | **unverified, check exists** | [12] |
| 19 | T4 | D. J. Samuel et al., "AgroLLM: Connecting farmers and agricultural practices through large language models," *AgriEngineering*, 8(1), art. 38, 2026. | Farmer Q&A | LLM + retrieval | Check | Contrast: knowledge Q&A, LLM writes facts; we template all numbers | **unverified, check exists** | [13] |

## Still to find (by Day 8)
- T1: one more Pakistan/Punjab vegetable price paper (try Pakistan J. Agric. Sci., Pakistan J. Agric. Res.,
  query "AMIS" / "Lahore market" / "tomato onion price Pakistan forecasting").
- T3: one paper on farmers' market choice with transport costs (lead: Zanello, Shankar, Srinivasan, AES 2012,
  northern Ghana).
- T4: one study on WhatsApp/voice advisory for farmers in South Asia.

## Comparison table (task 8.4, to do)
Systems: Namal FYP [3], Zarai Mandi [1], AMIS Punjab [2], Kissan helpline, MandiSaathi.
Columns: channel; data source; forecast? (horizon, uncertainty); where-to-sell after costs; harvest outlook;
voice/Urdu; evaluation reported.
