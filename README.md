# CoolHead

A school science project: **can a wet cloth canopy keep a flat concrete roof, and the room below it,
cooler?** The roof's temperature and the heat flowing into the room are modelled hour by hour
through a hot day in Faisalabad, Pakistan. The CoolHead canopy is compared with a bare roof, a
white-painted roof and a dry (shade-only) canopy.

> These are **computer-model results**, built from published physics and stated assumptions, not
> measurements. Two home experiments are planned to measure the cloth's most uncertain properties.

## What's here

| File | What it is |
|---|---|
| `app.py` | Interactive web app: sliders for weather, a v1/v2 model switch, charts and an animated roof cross-section |
| `coolhead_model.py` | The model: physics, settings, model versions v1 and v2, and `create_model()` |
| `coolhead_roof_model_v2.ipynb` | Notebook that runs the model and draws the presentation charts (imports `coolhead_model.py`) |
| `coolhead_roof_model.ipynb` | The original notebook (model v1 built in) |
| `model_readme.md` | How the model works: every formula, its source, and what changed in v2 and why |
| `initial_findings.md` | Review of the original model, with recommended fixes |
| `experiment_evap.md` | Experiment 1: how fast does wet cloth dry in the sun? (weighing) |
| `experiment_transp.md` | Experiment 2: how much sunlight gets through dry and wet cloth? (light sensor, optional Arduino) |
| `tests/` | Tests for the model and the app |
| `tools/screenshot.py` | Screenshots of every app tab (local or live), to check how it looks |
| `HANDOFF.md` | Project status, conventions and next steps for whoever continues the work |

## Model versions

- **v1**: the original notebook model.
- **v2** (default): v1 plus fixes from the review. Wet cloth lets more sun through, a wetness
  factor for the cloth, the roof's open sides see the surroundings instead of the sky, and the air
  under the canopy is modelled properly.

With v2, the wet canopy cuts the heat into the room by about **54%** on a hot June day, compared
with 74% in v1. That is about the same as white roof paint. See `model_readme.md` for the details.

## Getting started

Developed and tested with Python 3.14.

```bash
python -m venv env
source env/bin/activate            # Windows: env\Scripts\activate
pip install -r requirements-dev.txt
```

| Task | Command |
|---|---|
| Run the web app | `streamlit run app.py` → opens http://localhost:8501 |
| Run the tests | `pytest` |
| Set up app screenshots (one time) | `python -m playwright install chromium` |

There are two requirements files:
- `requirements.txt`: only what the web app needs. Streamlit Community Cloud installs this one.
- `requirements-dev.txt`: the above, plus tests, screenshots and running notebooks locally.

## Notebook in Google Colab

Upload `coolhead_roof_model_v2.ipynb` and `coolhead_model.py` to the same Colab folder, then
**Runtime → Run all**. Results land in the `coolhead_model_results` and `charts` folders. At the
top of the notebook, `MODEL_VERSION` switches between v1 and v2, and `SETTINGS_OVERRIDES` changes
any setting.

## Deploying the app

Deployed with [Streamlit Community Cloud](https://streamlit.io/cloud): **New app** → this repository →
branch `main` → main file `app.py`. Each push to `main` updates the app.
