"""Full-text routes: each one fetches the full text of a work from one legal source.

Routes are pure fetchers. They never record events and never raise for an HTTP or content
problem; the service that orders them decides what gets written.
"""
