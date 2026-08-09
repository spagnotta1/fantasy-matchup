"""Evaluation harnesses that measure the modelling layer against history.

Nothing in here is on a request path. These modules exist to produce evidence —
they read the frozen prediction foundation, replay it under a leakage boundary,
and score it. A production default changes only after one of them says it
should, and only by hand.
"""
