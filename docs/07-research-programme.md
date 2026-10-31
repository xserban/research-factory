# Research programme

Intersection of computational modelling, machine learning and medicine. Projects are linked and can have subprojects. Every project uses the same factory process; only the graph content, extraction fields and test types differ.

## Projects and dependencies
- **A. AI-assisted hybrid computational models for real-time TAVI and stenting interventions.**
- **B. Linear attention (as in LLMs) for vision models** — faster, scalable to larger models. Example research idea: *find the best linear attention mechanism for vision*.
- **C. 2D→3D angiographic reconstruction from biplanar angiograms** with deep learning.

Dependencies: B provides fast backbones → C provides patient-specific geometry → A needs speed and geometry during the procedure. Cross-project hypothesis example: does a linear-attention backbone make reconstruction fast enough for A's in-procedure loop?

## Example graphs (regions around each focus)

**A. PINN-based models for TAVI**
- Focus: physics-informed neural network models of TAVI / the aortic valve
- TAVI and aortic stenosis in general: clinical outcomes, imaging, procedure planning
- CFD and fluid–structure interaction of the aortic valve
- In-silico trials: methodology, credibility (ASME V&V 40), regulatory use
- PINNs and neural operators in other cardiovascular and engineering problems
- (Further candidates: reduced-order models, graph networks on meshes; real-time surrogates in other engineering fields)

**B. Best linear attention for vision**
- Focus: linear / efficient attention in vision models
- Efficient vision transformers (windowed attention, token pruning, hybrid convolution designs)
- Linear attention and relatives in language models, incl. state-space models
- Hardware-efficient kernels, low-rank approximation
- Vision benchmarks and evaluation protocols (fair speed/accuracy measurement)
- Note: "best" cannot be settled from published numbers (different training setups) → the factory must detect this and propose a controlled comparison.

**C. Biplanar 2D→3D reconstruction**
- Focus: deep learning reconstruction of 3D vessels from biplanar angiography
- Coronary CTA segmentation, 3D QCA, rotational angiography
- Sparse-view CT reconstruction, NeRF / Gaussian splatting for X-ray, implicit shape representations, diffusion priors
- Projective / epipolar geometry, vessel-tree and centreline models
- Analogues: cryo-EM / tomography, reconstruction of tree-like structures (neurons) from few views

Shared regions across projects (e.g. neural operators, implicit representations, efficient transformers) are built once.

## Extraction fields (examples)
- B: computational complexity, benchmark accuracy, throughput, memory, resolution, model size, training setup.
- A: physics encoded, data used, validation, run time, clinical endpoint.
- C: input views, geometry representation, metrics, datasets, phantoms vs. clinical data.

## Neurodegeneration (ND) — thesis case
The MSc thesis proposal (docs/thesis-proposal.pdf) uses AI for neurodegenerative diseases as the case study because a published expert review (Ciampi et al.) provides a gold standard. Open decision: keep ND as validation case and deploy on our programme (e.g. project C or B), or switch the thesis case study to our programme.

Thesis summary: 8 months, one student. WP1 setup & protocol (M1) · WP2 mapping review (M2–3) · WP3 extraction & gap analysis (M4–5) · WP4 hypotheses & falsification (M5–6) · WP5 evaluation (M6–7) · WP6 writing (M7–8). RQ1 review coverage/coding; RQ2 extraction accuracy with spans; RQ3 hypotheses vs. later literature + falsification; RQ4 integrity failures vs. deep-research baseline.
