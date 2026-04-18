# AI UAT Copilot

## Description

AI-assisted tool that turns unstructured requirements into structured UAT scenarios: acceptance criteria, test cases, steps, and execution-ready **DOCX** exports. It supports import from JSON or Word (`.docx`), a guided **AI Scenario Builder**, and a **review** workflow with traceability and coverage-oriented views.

## Features

- **Scenario context → structured generation** — narrative context drives ACs, test cases, and steps  
- **Multi-scenario support** — form-style, toggle/notification, and **action/event**-style flows (see `docs/schema.md`)  
- **Review system** — traceability, coverage gaps, reviewer focus (optional LLM), test-result tracking  
- **Execution draft DOCX export** — pre-review execution packet from the scenario builder  

## How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Use `requirements-dev.txt` only if you plan to run tests or development tooling.

## Environment setup

Optional OpenAI-powered features (traceability refinement, reviewer focus, polish, etc.) need an API key.

1. Copy the example env file:

   ```bash
   copy .env.example .env
   ```

   (On macOS/Linux: `cp .env.example .env`)

2. Edit `.env` and set:

   ```env
   OPENAI_API_KEY=your_api_key_here
   ```

3. Confirm `.env` is **not** committed (it is listed in `.gitignore`).

The app loads `.env` automatically when `python-dotenv` is installed (`load_dotenv()` in `app.py`). You can also set `OPENAI_API_KEY` in your shell or hosting provider’s secret manager.

## Tech stack

- Python, **Streamlit**, **pandas**, **python-docx**  
- **OpenAI** client + **python-dotenv** (optional) — keys only via environment / `.env`  
- See `requirements.txt` for pinned versions  

## Further documentation

- **Schema & fields:** `docs/schema.md`  
- **Changelog:** `CHANGELOG.md`  
- **DOCX intake notes:** `docs/intake_notes.md`  

## Publishing to GitHub

From a clean copy of the repo (no `.venv`, no `__pycache__`, no `.env`):

```bash
git init
git add .
git commit -m "Initial commit - AI UAT Copilot v1"
git branch -M main
git remote add origin https://github.com/<your-username>/ai-uat-copilot.git
git push -u origin main
```

Before pushing, search the tree for accidental secrets (e.g. `sk-`, pasted keys). This repository is intended to contain **no** real API keys in tracked files.
