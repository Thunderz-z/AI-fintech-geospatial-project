# FinGuard Dataset Research

Status: research complete for prioritization; **nothing downloaded yet**. Access terms and
exact sizes must be verified at acquisition time (Kaggle terms in particular are
accept-to-download and cannot be fetched automatically). Machine-readable manifest:
[`data/manifests/finguard-manifest.yaml`](../../data/manifests/finguard-manifest.yaml).

## Priority 1 — IBM AML synthetic transaction datasets (HI-Small, LI-Small)

- Origin: IBM synthetic transaction generation for AML research — introduced in Weber et al.,
  *"Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for
  Financial Forensics"* (2019); distributed via Kaggle ("IBM-AML" / IBM Tabformer datasets) —
  verify the exact listing and its terms before download
- Content: synthetic transaction CSVs (timestamp, sender/receiver accounts, amount, currency,
  payment type, is-laundering flag) with **planted AML typologies** (fan-in/fan-out, cycle,
  stack, scatter-gather, gathering-distributing) — ideal for graph motif detection and
  typology-labelled evaluation
- Sizes *(approx., verify)*: LI-Small ≈ tens of MB; HI-Small ≈ 250 MB CSV / ~5.2 M
  transactions. Larger variants (HI/LI-Medium/Large) exist up to tens of GB — **not in initial
  scope**
- Use: transaction graph construction, motif detectors evaluated against planted typologies,
  supervised fraud baseline with temporal splits
- License/terms: research-oriented distribution — record exact terms + acceptance state in the
  manifest at download

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
