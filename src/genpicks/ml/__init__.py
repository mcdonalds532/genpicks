"""Feature building, model training and evaluation.

Everything here reads the clean relational layer (never data/raw) and is
deterministic given the database state. Feature builders are single
chronological passes that read running state before updating it with the
match result, so a feature can never see its own or any later match.
"""
