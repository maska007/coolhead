from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "app.py")
TIMEOUT = 120


def app():
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def set_version(at, version):
    radio = at.radio(key="version")
    radio.set_value(next(o for o in radio.options if o.startswith(version))).run(timeout=TIMEOUT)
    return at


def test_app_runs_with_default_model():
    at = app()
    assert not at.exception
    assert at.radio(key="version").value.startswith("v2")
    assert "Model **v2**" in at.caption[0].value
    assert len(at.metric) == 4


def test_switch_to_v1_changes_results():
    at = app()
    v2_heat = at.metric[2].value
    set_version(at, "v1")
    assert not at.exception
    assert at.metric[2].value != v2_heat
    assert "Model **v1**" in at.caption[0].value


def test_v2_only_settings_hidden_for_v1():
    at = app()
    assert any("Wetness factor" in n.label for n in at.number_input)
    set_version(at, "v1")
    assert not any("Wetness factor" in n.label for n in at.number_input)


def test_invalid_setting_shows_error():
    at = app()
    dt = next(n for n in at.number_input if n.label.startswith("Time step"))
    dt.set_value(300.0).run(timeout=TIMEOUT)
    assert at.error and "time step too long" in at.error[0].value


def test_no_cases_selected():
    at = app()
    at.multiselect[0].set_value([]).run(timeout=TIMEOUT)
    assert not at.exception
    assert "at least one case" in at.info[0].value
