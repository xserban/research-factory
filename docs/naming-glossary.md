# Naming glossary: philosophy-of-science names for factory objects

Status: proposal, not adopted (2026-11-14). Background only; not binding. No code, event, tool or hub name changes because of this page. Adopting a name needs a decision entry in `docs/decisions.md`.

## Scope

- **Objects only.** Things the factory produces or holds (records, findings, layers, principles) get a name taken from the philosophy of science. Roles and agents (searchers, screeners, miners, builders) keep plain names.
- **Display vocabulary only, if ever adopted.** Event types are stored in the append-only log (`00-system.md`); renaming them would require projector aliases for every existing event. Any adoption would start with the hub, skills and documentation, leaving code identifiers unchanged.

## Glossary

| Factory object | Proposed name | Source | Why it fits |
|---|---|---|---|
| seeds | **exemplars** (held-out seeds: *hidden exemplars*) | Kuhn, *Structure of Scientific Revolutions* (1962), postscript 1969 | A field is learned through its exemplary solved problems; seeds are the known-relevant works the search must recover. |
| contradictions (finder output) | **anomalies** | Kuhn (1962) | Results that do not fit the received view and that drive revision. |
| convergence of independent evidence in the evidence report | **consilience** | Whewell, *Philosophy of the Inductive Sciences* (1840) | Independent inductions agreeing on one conclusion. |
| consolidation of cards | **colligation** | Whewell (1840) | Binding scattered facts together under one conception. |
| core and adjacent layers | **hard core** and **protective belt** | Lakatos, "Falsification and the methodology of scientific research programmes" (1970) | A programme's central commitments and the auxiliary layer around them. |
| regions (if a region is one line of work) | **programmes** | Lakatos (1970) | A sequence of works sharing a hard core. |
| background concepts | **auxiliary assumptions** | Duhem (1906); Quine, "Two dogmas of empiricism" (1951) | No hypothesis is tested alone; it is tested together with its background. |
| interpretations | **readings** (theory-laden) | Hanson, *Patterns of Discovery* (1958) | Observation is already interpretation. |
| intuition layer | **tacit layer** | Polanyi, *The Tacit Dimension* (1966) | "We can know more than we can tell." |
| vocabulary and concept merging | **trading zone** | Galison, *Image and Logic* (1997) | A shared working language between communities that keep their own. |
| hypotheses (registered) | **conjectures** | Popper, *Conjectures and Refutations* (1963) | Bold claims stated before testing. |
| experiments | **severe tests** | Mayo, *Error and the Growth of Experimental Knowledge* (1996) | A test that would probably have failed if the claim were false. |
| a decision between two rival hypotheses | **crucial instance** (*instantia crucis*) | Bacon, *Novum Organum* (1620), II.36 | A case that decides between two explanations. |
| audit and calibration findings, by kind of error | **Idols**: Tribe (bias shared by the model), Cave (one agent's bias), Market (ambiguous wording), Theatre (bias inherited from a school of thought) | Bacon, *Novum Organum* I.38–44 | A classification of error sources; could serve as an audit finding category. |
| miner run on one work; calibration gold set | **assay**; **reference standard** | Galileo, *Il Saggiatore* (1623) | Measuring what a sample contains against a known standard. The role name *miner* is kept. |
| append-only events, corrections supersede | **Neurath's boat** (name of the principle) | Neurath, "Protokollsätze" (1932) | The ship is rebuilt at sea, plank by plank; nothing is rebuilt from dry dock. |
| trace | **virtual witness** | Shapin and Schaffer, *Leviathan and the Air-Pump* (1985) | Reporting an experiment so that readers can witness it without being present. |
| check | **nullius in verba** | Royal Society motto (1663) | Take nobody's word for it. |
| hub | **centre of calculation** | Latour, *Science in Action* (1987) | The place where inscriptions from many sites are gathered and combined. |
| inbox and discovery record / evidence report | **context of discovery** / **context of justification** | Reichenbach, *Experience and Prediction* (1938) | How a candidate arrived is separate from whether it holds. |
| review gates | **organised scepticism** | Merton, "The normative structure of science" (1942) | Claims are held back until scrutinised. |
| notices (retractions, newer versions) | **fallibilism** | Peirce (1897) | Every conclusion stays open to revision. |
| protocol | keep **protocol** | Carnap, Neurath: protocol sentences (1932) | The name already belongs to this tradition. |

## Open points

- Whether *programmes* fits regions depends on what a region holds; confirm against `services/modules/regions.py`.
- *Idols* as an audit category would be a schema change (a new field on audit findings), not only a name.
