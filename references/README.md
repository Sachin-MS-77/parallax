# Locally supplied reference data

`ofac-historical.csv` contains one Bitcoin address published in OFAC's
[28 November 2018 notice](https://ofac.treasury.gov/recent-actions/20181128),
checked against the official page on 25 September 2026. It is a **historical
reference**, not a complete or current SDN list. PARALLAX does not fetch updates
at runtime. Only the public address, source URL, currency and historical date
are included; no personal identifiers are needed.

```bash
parallax references --db data/my-case/case.sqlite --file references/ofac-historical.csv --kind seeds
parallax score --db data/my-case/case.sqlite --model data/my-case/model
```

Exchange references use the same CSV fields `address,source,currency` with
`--kind exchanges`. Supply independently maintained local references. The
application does not infer KYC records from transaction sizes.

Common-input clustering follows Meiklejohn et al. (IMC 2013),
[A Fistful of Bitcoins](https://cseweb.ucsd.edu/~smeiklejohn/files/imc13.pdf).
Collaborative transactions can invalidate the ownership heuristic, so clusters
are candidate entities and equal-output collaborative shapes are excluded.

[Weber et al. (2019)](https://arxiv.org/abs/1908.02591) describes the Elliptic
transaction graph and classification experiment. Its anonymized graph is not a
named real laundering case and does not supply PARALLAX's network observations.
The existing DOJ-inspired pattern replay is synthetic and must not be relabelled
as an Elliptic reconstruction. A real external topology cross-check remains
dependent on a cited edge list and its permitted local use.
