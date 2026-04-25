# Public data sources (training vs. demo / validation)

| Role | Source | Suggested use in this app |
| --- | --- | --- |
| **Sand / illegal extraction as a research case** | [Mekong Delta: extent of illegal sand mining (Communications Earth & Environment, 2023)](https://www.nature.com/articles/s43247-023-01161-1) and linked repositories (e.g. [WUR data listing](https://research.wur.nl/en/publications/extent-of-illegal-sand-mining-in-the-mekong-delta/datasets/)) | **Methods + regional baselines**; not a global label layer you import directly into a generic GeoJSON—verify licensing and field alignment before any supervised model. **Demo / validation only** for global AOI support. |
| **Monitoring projects (code + method references)** | [Global Policy Lab — Sand Mining Watch](https://www.globalpolicy.science/sand-mining-watch) | **Feature design and review workflows**; compare your z-score / time-split logic to their indicators. **Reference**, not a packaged training set for this stack. |
| **Water and river surface (segmentation, width proxies)** | [RiverScope (high-res river masking, Zenodo)](https://zenodo.org/records/15376394), [S1S2-Water (S1+S2 water body masks)](https://zenodo.org/records/11278238), [Sentinel River Segmentation Dataset (GitHub)](https://github.com/radekszostak/sentinel-river-segmentation-dataset) | **Offline U-Net or baseline masks** to improve MNDWI robustness; labels are “water/river,” **not** “illegal.” Use for **pretraining** or ablations if you add Phase C. |

**Licensing:** confirm each provider’s terms before redistributing tiles or training chips. This repository’s GEE path uses public Sentinel collections in Earth Engine; production use of Zenodo/CSV exports needs a separate check.

**Alignment with the app’s disclaimer:** the FastAPI/GEE pipeline returns **morphology / backscatter z-scores** in your AOI, not a legal “illegal” classification, unless you add permits and labeled validation yourself.
