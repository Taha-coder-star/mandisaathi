PYTHON ?= python

# Gate G3 (task 13.4): `make results` regenerates every results CSV identically from the commit.
# Each recipe is one python command, so Windows without make can run the same line directly.
.PHONY: results
results:
	$(PYTHON) -m scripts.score_e2 --out results
