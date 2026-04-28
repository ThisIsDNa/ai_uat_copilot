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

## Sample Workflow

<img width="1920" height="1002" alt="Step 2" src="https://github.com/user-attachments/assets/100ca15d-8dfe-41bd-b39a-b9b9944ada3e" />
<img width="1920" height="924" alt="Step 3" src="https://github.com/user-attachments/assets/be8e9ec9-8a1e-40cf-8cb3-be1eb1855307" />
<img width="1920" height="921" alt="Step 4" src="https://github.com/user-attachments/assets/d879d383-e899-4dc1-9f6a-93f6edaff799" />
<img width="1920" height="921" alt="Step 5" src="https://github.com/user-attachments/assets/aea6405a-a976-418b-bd02-6b44a9180183" />
<img width="377" height="884" alt="Step 6" src="https://github.com/user-attachments/assets/e4d7bab0-0874-4f3d-b265-529b5ce2dd2c" />
<img width="1920" height="920" alt="Step 7" src="https://github.com/user-attachments/assets/2532d0fc-8e8d-4f26-bdd4-fb8e4869a151" />
<img width="376" height="886" alt="Step 8" src="https://github.com/user-attachments/assets/d4bcf388-6e63-4fb6-9e09-00b0310fe152" />
<img width="378" height="574" alt="Step 9" src="https://github.com/user-attachments/assets/edf8980f-66c0-4864-ae6e-1a3ba15298b1" />
<img width="1920" height="921" alt="Step 10" src="https://github.com/user-attachments/assets/fe650135-1217-4097-adcc-ff0aa7260bff" />
<img width="378" height="884" alt="Step 11" src="https://github.com/user-attachments/assets/d38311e1-1120-423c-be30-b44b12d74891" />
<img width="1920" height="921" alt="Step 12" src="https://github.com/user-attachments/assets/98bcdccc-a1ca-4873-80f2-1ab69dd29ceb" />
<img width="1920" height="922" alt="Step 13" src="https://github.com/user-attachments/assets/bb32e7c5-53f2-48c5-9d59-e03dab991660" />
<img width="1920" height="894" alt="Step 14" src="https://github.com/user-attachments/assets/21c01de4-7c77-43d2-a795-d76524055409" />
<img width="1920" height="920" alt="Step 15" src="https://github.com/user-attachments/assets/5d2fd729-3f14-418d-85c5-08033402010d" />
<img width="1920" height="921" alt="Step 16" src="https://github.com/user-attachments/assets/3f2df2c4-d243-4075-a963-54078f67ae17" />
<img width="1920" height="922" alt="Step 17" src="https://github.com/user-attachments/assets/785b300f-effb-4b05-9d0b-d3f8e8535337" />
<img width="1920" height="920" alt="Step 18" src="https://github.com/user-attachments/assets/c156a27b-64bb-4e11-885c-39c7d3a72901" />
