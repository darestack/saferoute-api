"""Service layer for SafeRoute API.

Extracted from route handlers to keep ``app/routes`` thin and focused on
HTTP concerns. Each module encapsulates a cross-cutting concern:

* ``circuit_breaker`` — state machine for failing fast on dead downstreams.
* ``route_cache`` — in-memory route lookup cache with single-flight fills.
* ``retry_processor`` — background retry queue consumer.
* ``retention`` — periodic cleanup of expired rows.
"""
