PYTHON ?= python

test:
	$(PYTHON) -m unittest discover -s tests -v
