"""Miner specifications: pure data, validation, compilation to packs and selection (slice M, M-C).

Invariants: nothing here reads an index, an event log or a model; a spec compiles to a `Pack`
and to kind checks by pure functions, and the same spec always gives the same digest.
"""
