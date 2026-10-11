"""D&D module domain layer.

The dataset model and the validator's check report join this package in the
storage/validator groups of add-dnd-module-foundation. Domain code holds
pure data and rules: no Qt, no SQLAlchemy session, no presentation imports
(pinned by the layer guards in ``tests/test_architecture_layers.py``, which
count this subtree since task 1.3).
"""
