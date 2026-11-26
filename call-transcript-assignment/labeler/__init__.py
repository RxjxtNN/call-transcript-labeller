"""Call labeling for the Anthropod assignment (policy assignment-v2).

Flow: transcript -> numbered turns -> model answers small evidence questions (passes.py)
-> Python applies the workbook rules (decisions.py, callbacks.py) -> one prediction (finalize.py).
"""
