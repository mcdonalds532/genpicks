"""Read-only HTTP API over the predictions database.

The API never computes predictions on request: python -m genpicks.ml.predict
writes them, this layer serves them. Keeps request latency flat and makes
the public track record auditable (predictions are append-only).
"""
