# FinGuard Dataset Research

Status: IBM AML listing **verified** (Kaggle page read directly, 2026-10-31); PaySim and
IEEE-CIS remain research-stage. **Nothing downloaded yet.** Machine-readable manifest:
[`data/manifests/finguard-manifest.yaml`](../../data/manifests/finguard-manifest.yaml).

## Priority 1 — IBM AML synthetic transaction datasets (HI-Small, LI-Small)

**Verified 2026-10-31 from the live Kaggle listing and IBM's official repository:**

- Listing: [`IBM Transactions for Anti Money Laundering (AML)`](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml),
  owner Erik Altman / IBM (`ealtman2019`); IBM's official
  [IBM/AML-Data](https://github.com/IBM/AML-Data) repo points to this Kaggle listing as the
  current ("new and improved") distribution. Silver-medal dataset, usability 9.41, updated
  ~2025 (listing says "a year ago").
- License: **CDLA-Sharing-1.0** ([Community Data License Agreement — Sharing 1.0](https://cdla.io/sharing-1-0/)) —
  shown on the Kaggle listing and stated in the IBM/AML-Data README (the GitHub repo code is
  Apache-2.0 but *the data is CDLA-Sharing-1.0*). Permissive: use/modification/redistribution
  (including commercial) allowed with attribution notice + license text when shared. Kaggle
  account terms acceptance still applies at download (accept-to-download by the account owner).
- Schema (11 columns, from Kaggle's own file metadata): `Timestamp` (Year/Month/Day
  Hour/Minute), `From Bank` (numeric bank code), `Account` (hex sender account), `To Bank`
  (numeric bank code), `Account.1` (hex receiver account), `Amount Received` (float, in
  Receiving Currency units), `Receiving Currency`, `Amount Paid` (float, in Payment Currency
  units), `Payment Currency`, `Payment Format` (cheque/ACH/wire/credit card/...),
  `Is Laundering` (0/1).
- Verified file sizes (as shown in the Kaggle file listing, uncompressed):
  - `HI-Small_Trans.csv` — **475.66 MB** (≈ 5 M transactions per the data card)
  - `HI-Small_Patterns.txt` — 323.84 kB
  - `LI-Small_Trans.csv` — **650.42 MB** (≈ 7 M transactions per the data card)
  - `LI-Small_Patterns.txt` — 99.16 kB
  - ⚠️ These supersede the earlier estimates ("LI-Small ≈ tens of MB", "HI-Small ≈ 250 MB") —
    those described the *original* 2019 Box release, not the current regenerated Kaggle files.
- ⚠️ **`LI-Small_Trans.csv` (650.42 MB) exceeds the portfolio's 500 MB per-download gate** —
  acquisition requires explicit owner approval (which the owner's manual download step
  constitutes, recorded in the manifest).
- Data card statistics (generator targets, to verify against the actual files at download):
  HI-Small ≈ 5 M tx / ~5.1 K laundering (1 per 981), ≈ 515 K accounts; LI-Small ≈ 7 M tx /
  ~4.0 K laundering (1 per 1,942), ≈ 705 K accounts. Primary activity window: **2022-09-01 to
  2022-09-10** (10 days) for both Small datasets.
- Known quirk (flagged in the listing's discussion #427517): some transactions fall **after**
  the stated date window, and those are all laundering — the temporal split utility must
  account for this when slicing train/valid/test.
- Planted typologies: 8 laundering patterns from AMLSim (Suzumura & Kanezashi) enumerated in
  the `*_Patterns.txt` files (fan-in, fan-out, cycle, stack, gather-scatter, ...); not all
  laundering in the data follows one of the 8 patterns.
- Recommended split (listing authors): **chronological 60/20/20** train/validation/test —
  consistent with ADR-0006.
- Citation requested by the authors: Altman et al., *"Realistic Synthetic Financial
  Transactions for Anti-Money Laundering"* ([arXiv:2306.16424](https://arxiv.org/abs/2306.16424),
  NeurIPS 2023); [IBM/Multi-GNN](https://github.com/IBM/Multi-GNN) for GNN baselines; earlier
  origin: Weber et al. 2019, *"Anti-Money Laundering in Bitcoin: Experimenting with Graph
  Convolutional Networks for Financial Forensics"*.
- Larger variants (HI/LI-Medium/Large) exist up to ~30 GB total — **not in initial scope**.

## Priority 2 — PaySim

- Origin: PaySim, López-Rojas & Axelsson (2016) — synthetic mobile-money simulator output;
  distributed via Kaggle — verify listing/terms
- Content: ~6.3 M transactions *(approx.)*, 11 columns (type, amount, balances, fraud flag,
  etc.), CSV ≈ 190 MB *(approx., verify)*
- Use: transaction fraud classification baseline (imbalance-aware), feature-engineering
  demonstrations
- Limitations: no account-level graph structure suitable for AML motifs; fraud flag is the
  only label; well-known dataset — no novelty by itself, pairs with IBM AML for the graph story

## Priority 3 — IEEE-CIS Fraud Detection (deferred)

- Origin: IEEE-CIS Vesta fraud detection Kaggle competition
- Access: requires Kaggle account + **competition rules acceptance**; NOT downloaded
  automatically — deferred until the initial FinGuard pipeline is operational
- Content: ~590k rows, 400+ features, real e-commerce transactions (identity + transaction
  tables ≈ 1–2 GB uncompressed *(approx., verify)*)
- Use (later): realistic large-scale fraud feature engineering benchmark

## Data acquisition principle

Start with the smallest representative subset (LI-Small first, then HI-Small), build complete
reproducible pipelines, scale only if a pipeline demonstrably needs more. No dataset work
proceeds without a manifest entry and free-space check; ≤ 5 GB initial budget; no single
download > 500 MB without explicit approval.

## Honesty requirements

- Synthetic data results must always be labelled synthetic; no claim of real-world fraud
  detection performance
- The IBM AML "is-laundering" flag labels **planted typologies**; detectors evaluated against it
  are being measured at recovering planted patterns — not at catching real criminals
- License/attribution recorded per dataset in the manifest before first use
