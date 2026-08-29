.PHONY: dev test seed sign-demo

dev:
	docker compose up --build

test:
	cd backend && pytest -q
	cd frontend && npm test -- --run

seed:
	cd backend && python -m app.seed

sign-demo:
	cd backend && python -m app.sign_csv ../data/demo-sales.csv

