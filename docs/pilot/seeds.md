# Pilot seeds — best linear attention mechanism for vision models

Status: draft · 2026-10-31 · Project B (`linear-attention-vision`), rigor mode `pilot`. Manual pilot: no platform code yet; this file and [log.md](log.md) stand in for `seed_add` events.

All arXiv IDs below were checked against the arXiv abstract page on 2026-10-31, except where marked *(memory)*.

## How the seeds are used
| Stage | Use | Requirement |
| --- | --- | --- |
| Question and protocol | Boundary rulings become criteria or non-goals with a recorded parent; every development positive must pass the draft criteria, and every negative must fail on a named criterion | R-10, R-11 |
| Scope probe | Development positives measure query recall per source (target ≥ 0.9); negatives indicate screening burden; vocabulary is harvested from development seeds | R-20 |
| Screening | Resolved boundary cases and some development seeds serve as worked examples; calibration is scored only on records **not** used as examples | R-34, R-35 |
| After search | Seed check (development and held-out); held-out recall is the reported figure; seeds detect false merges and splits; included seeds start citation chasing | R-24, R-25, R-26 |

## Development / held-out split
- **Rule:** about one third of positives are held out, stratified by period (≤ 2025: 4 of 11; 2026: 1 of 4). Negatives and boundary cases are not held out in the pilot.
- **Procedure:** `random.Random(20261031)`, `sample(SEED01..SEED11, 4)` then `sample(SEED12..SEED15, 1)`; Python 3.10.12; drawn 2026-10-31 by Claude on the researcher's machine.
- **Held-out seeds:** SEED02, SEED04, SEED05, SEED07, SEED12. Details are in [heldout-seeds.md](heldout-seeds.md). **Do not open that file while drafting queries, criteria or worked examples.**
- **Known limitation:** the session that drew the split had already seen all candidates. Query drafting must therefore happen in a fresh session that has not read `heldout-seeds.md` or this conversation. Record the session in the log.

## Development positives
| ID | Paper | arXiv | Venue | Why in scope |
| --- | --- | --- | --- | --- |
| SEED01 | EfficientViT: Multi-Scale Linear Attention for High-Resolution Dense Prediction | 2205.14756 | ICCV 2023 | ReLU linear attention for high-resolution dense prediction |
| SEED03 | Agent Attention: On the Integration of Softmax and Linear Attention | 2312.08874 | ECCV 2024 | Softmax–linear hybrid; classification, detection, generation |
| SEED06 | SOFT: Softmax-free Transformer with Linear Complexity | 2110.11945 | NeurIPS 2021 | Softmax-free linear-complexity attention for vision |
| SEED08 | Breaking the Low-Rank Dilemma of Linear Attention (RALA) | 2411.07635 | CVPR 2025 | Rank augmentation of linear attention in vision backbones |
| SEED09 | Castling-ViT | 2211.10526 | CVPR 2023 | Softmax in training, linear-angular attention at inference |
| SEED10 | ViG: Linear-complexity Visual Sequence Learning with Gated Linear Attention | 2405.18425 | AAAI 2025 | Gated linear attention for vision |
| SEED11 | Separable Self-attention for Mobile Vision Transformers (MobileViTv2) | 2206.02680 | TMLR 2023 | Linear-in-tokens separable self-attention (subject to ruling Q2) |
| SEED13 | LinearSR: Unlocking Linear Attention for Stable and Efficient Image Super-Resolution | — (not found yet) | ICLR 2026 | Linear attention for image restoration |
| SEED14 | Rethinking Vision Architectures with Gated Linear Attention and KAN (LKAT) | 2609.22506 | preprint 2026 | Chunk-wise gated linear attention ViT |
| SEED15 | Exact Linear Attention | 2605.18848 | preprint 2026 | Exact kernel decomposition; evaluated in a detector (YOLO-LAT) |

## Negative look-alikes
| ID | Paper | arXiv | Why it is a look-alike |
| --- | --- | --- | --- |
| NEG01 | Swin Transformer | 2103.14030 *(memory)* | Efficient ViT, but windowed softmax attention |
| NEG02 | Linformer: Self-Attention with Linear Complexity | 2006.04768 | Linear complexity via low-rank projection; NLP only |
| NEG03 | Vision Mamba (Vim) | 2401.09417 | Linear-cost vision via a state-space model (subject to ruling Q4) |
| NEG04 | FlashAttention | 2205.14135 | Exact quadratic attention; IO-aware speed-up |
| NEG05 | Token Merging: Your ViT but Faster (ToMe) | 2210.09461 | Fewer tokens; attention unchanged |

## Boundary cases (pending rulings)
| ID | Paper | arXiv | Ruling it depends on |
| --- | --- | --- | --- |
| B1 | Transformers are RNNs (Katharopoulos et al., ICML 2020) | 2006.16236 | Q3 origin papers |
| B2 | Rethinking Attention with Performers | 2009.14794 *(memory)* | Q3 origin papers |
| B3 | SANA: linear diffusion transformer | 2410.10629 | Q1 generation |
| B4 | XCiT: Cross-Covariance Image Transformers | 2106.09681 | Q2 mechanism (channel attention) |
| B5 | Linearizing Vision Transformer with Test-Time Training | 2605.02772 | Q1 generation, Q2 mechanism (TTT layers) |
| B6 | Representative Attention for Vision Transformers | 2605.14913 | Q2 mechanism (token compression) |
| B7 | Do ViTs Need All-to-All Attention? Elastic Learned Cores (VECA) | 2605.12491 | Q2 mechanism (core tokens) |
| B8 | Gated DeltaNet-2 | 2605.22791 | Q3 origin papers (language) |
| B9 | ELSA: Exact Linear-Scan Attention (CVPR 2026) | not found | Probably exact attention (NEG-like); abstract not yet checked |

## Rulings to make (become non-goals / criteria)
| Q | Question | Decides | Ruling |
| --- | --- | --- | --- |
| Q0 | Date window: 2020–2026 with a ≥ 2025 subgroup, or 2025–2026 only | search limits | *open* |
| Q1 | Does "vision" include generative models (diffusion, super-resolution, text-to-image)? | B3, B5, SEED13 | *open* |
| Q2 | Is "linear attention" restricted to kernel/feature-map replacements of softmax, or any attention linear in token count (channel, separable, compression, cores, TTT)? | B4–B7, SEED11 | *open* |
| Q3 | Are general (non-vision) linear-attention papers in scope if they report vision experiments? | B1, B2, B8 | *open* |
| Q4 | Are state-space / gated recurrent hybrids in scope (cf. SEED04's argument)? | NEG03 | *open* |

After a ruling, move affected boundary cases to development positives or negatives (new IDs; never renumber), record the move in the log.
