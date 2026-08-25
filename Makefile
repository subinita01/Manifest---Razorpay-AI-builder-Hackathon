VENV := .venv
# Prefer a versioned 3.11+ interpreter; fall back to whatever python3 is on
# PATH (the version guard below fails loudly rather than silently building a
# venv on too old a Python, e.g. macOS system Python 3.9).
PYTHON_BIN := $(shell command -v python3.11 2>/dev/null || command -v python3.12 2>/dev/null || command -v python3.13 2>/dev/null || command -v python3 2>/dev/null)
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: install test lint demo-data demo eval clean

$(PYTHON):
	@if [ -z "$(PYTHON_BIN)" ]; then \
		echo "No python3 interpreter found on PATH."; exit 1; \
	fi
	@$(PYTHON_BIN) -c "import sys; assert sys.version_info >= (3, 11)" || \
		(echo "MANIFEST requires Python 3.11+; $(PYTHON_BIN) is older."; \
		 echo "Install one (e.g. 'brew install python@3.11') and retry, or run: make install PYTHON_BIN=/path/to/python3.11"; \
		 exit 1)
	$(PYTHON_BIN) -m venv $(VENV)

install: $(PYTHON)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .

demo-data:
	$(PYTHON) -m data.generator --seed 42 --orders 600 --out data/demo/

demo:
	$(PYTHON) -m streamlit run app/streamlit_app.py

eval:
	$(PYTHON) -m evaluation.ablation

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
