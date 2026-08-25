.PHONY: install test lint demo-data demo eval clean

install:
	pip install -r requirements.txt

test:
	pytest

lint:
	ruff check .
	black --check .

demo-data:
	python -m data.generator --seed 42 --orders 600 --out data/demo/

demo:
	streamlit run app/streamlit_app.py

eval:
	python -m evaluation.ablation

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
