# Medical Diagnosis Expert System

A rule-based expert system that asks a patient about their symptoms and narrows the answers down to one of **31 diseases**, then shows the treatment information for that disease and offers it as a downloadable PDF.

The project runs in two ways from the same rule base: a **web application** in the browser, and a **console application** in the terminal.

**Author:** Abid Shahoriar
**Course:** CSE 440 — Artificial Intelligence
**Repository:** `cse440-g3-medical-diagnosis`

---

## Table of contents

1. [Requirements](#requirements)
2. [Setup](#setup)
3. [Running the project](#running-the-project)
4. [Project structure](#project-structure)
5. [How the diagnosis works](#how-the-diagnosis-works)
6. [Diseases covered](#diseases-covered)
7. [Troubleshooting](#troubleshooting)
8. [Disclaimer](#disclaimer)

---

## Requirements

### Software

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.8 or newer | Tested on Python 3.14.3 |
| pip | Any recent version | Ships with Python |
| Web browser | Any modern browser | Needed for the web application |

### Python packages

| Package | Version | Purpose |
|---|---|---|
| `Flask` | 3.1.3 | Serves the web application |
| `experta` | 1.9.4 | Forward-chaining rule engine |
| `frozendict` | 1.2 | Required by `experta`, installed automatically |
| `schema` | Latest | Required by `experta`, installed automatically |

No other libraries are needed. The PDF export is written from scratch in `web.py`, so no PDF library has to be installed.

---

## Setup

### Step 1 — Get the project

```
git clone https://github.com/GaZiPR0/cse440-g3-medical-diagnosis.git
cd cse440-g3-medical-diagnosis
```

If you already have the folder, just open it in a terminal.

### Step 2 — Create a virtual environment

Keeping the packages in a virtual environment avoids clashes with other projects on the same machine.

**Windows**

```
python -m venv venv
venv\Scripts\activate
```

**macOS and Linux**

```
python3 -m venv venv
source venv/bin/activate
```

The prompt shows `(venv)` once the environment is active.

### Step 3 — Install the packages

```
pip install flask experta
```

`experta` pulls in `frozendict` and `schema` on its own.

### Step 4 — Check the installation

```
python -c "import expert; print(expert.EXPERTA_AVAILABLE)"
```

This must print `True`. If it prints `False`, the rule engine did not load — see [Troubleshooting](#troubleshooting).

---

## Running the project

### Web application (recommended)

```
python web.py
```

The server starts on port 5000 and opens the browser automatically. If it does not open, go to:

```
http://localhost:5000
```

Press `Ctrl+C` in the terminal to stop the server.

In the browser you can:

- answer one question at a time, with the next question chosen from your previous answers
- go back and change any earlier answer, after which the questions are asked again from that point
- read the full treatment document for the diagnosed disease
- download that treatment document as a PDF

### Console application

```
python expert.py
```

The same questions are asked in the terminal. Answer `yes` or `no`, and for multiple-choice questions type the numbers of every option that applies, separated by spaces. When a disease is identified you are asked whether to open its treatment page in the browser.

---

## Project structure

```
cse440-g3-medical-diagnosis/
├── expert.py             Rule base, diagnosis engine and console application
├── web.py                Flask web application, page templates and PDF writer
├── symptoms.ods          Spreadsheet of all 31 diseases and their symptoms
├── diseases_list.txt     Plain list of the diseases and their question branches
├── README.md             This file
└── Treatment/
    ├── markdown/         Treatment document for each disease, in Markdown
    └── html/             The same documents in HTML, with pandoc.css
```

### The two main files

**`expert.py`** holds the knowledge base.

- `MedicalExpert` — the `experta` knowledge engine holding every rule
- `diagnose_from_answers()` — the same rules as a plain function, so the answers can be evaluated without running the engine
- `DiagnosisFlow` — replays the engine to find the next unanswered question, which is what lets the web application ask them one at a time
- `suggest_disease()` — reports the result and opens the treatment page

**`web.py`** holds the interface.

- The landing, questionnaire and result pages
- JSON endpoints for fetching a question, submitting an answer and revising an earlier answer
- A reader that strips the pandoc wrapper from the treatment HTML so it matches the site styling
- A PDF writer that lays the treatment document out with headings, bullets, callouts and page footers

---

## How the diagnosis works

The system does not guess and does not use any trained model. Every answer is matched against written rules, so the same answers always give the same result.

1. **Medical history** — existing conditions such as diabetes, hypertension, heart disease or a thyroid disorder are recorded first. A known condition lowers the number of symptoms needed for the related disease to match.
2. **Main symptoms** — red eyes, fatigue, shortness of breath, loss of appetite and the type of fever are asked next. These answers choose which branch of questions to follow.
3. **Branch questions** — each branch asks about the symptoms of the diseases in that group only, so an answer about fever is never followed by an unrelated question.
4. **Threshold** — a disease is reported when enough of its symptoms are present. Where two diseases share a branch, salience decides which is tested first, so the more specific one is offered before the general one.
5. **Result** — the disease and the matched symptoms are shown, with its treatment document.

---

## Diseases covered

The rule base covers 31 diseases:

| Group | Diseases |
|---|---|
| Eye conditions | Conjunctivitis, Eye Allergy, Dry Eye Syndrome |
| Fever driven | Dengue, Typhoid, Chikungunya, Bronchitis, Sinusitis, Common Cold, Tuberculosis, Influenza, Hepatitis, Pneumonia, Malaria, AIDS, Pancreatitis, Corona Virus, Urinary Tract Infection, Gastroenteritis |
| Breathing and heart | Asthma, COPD, Obesity, Anemia, Coronary Arteriosclerosis |
| Digestive | Peptic Ulcer, Gastritis |
| Metabolic and other | Diabetes, Dehydration, Hypothyroidism, Hyperthyroidism, Arthritis |

`diseases_list.txt` lists all of them with the question branch each one belongs to, and `symptoms.ods` holds the full symptom list for each.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'flask'` or `'experta'`**
The virtual environment is not active, or the packages were installed into a different Python. Activate the environment and run `pip install flask experta` again.

**`EXPERTA_AVAILABLE` prints `False`**
`experta` did not import. Reinstall it with `pip install --force-reinstall experta`. Note that `experta` depends on an old version of `frozendict` that refers to `collections.Mapping`, which was removed in Python 3.10. `expert.py` restores those names at the top of the file before importing `experta`, so this is handled already and no downgrade of Python is needed.

**Port 5000 is already in use**
Another program is on that port. Stop it, or change the last line of `web.py` to a free port, for example `app.run(debug=False, port=5050)`.

**The browser does not open by itself**
Open `http://localhost:5000` manually while the server is running.

**A treatment page is missing**
Check that the `Treatment/html` and `Treatment/markdown` folders were downloaded with the project, and that the file is named exactly after the disease.

---

## Disclaimer

This project was built for academic purposes. It is not a medical device and must not be used for real diagnosis or treatment. Always consult a qualified doctor for medical advice.
