import dataclasses
from functools import lru_cache

import numpy as np
import pytest

import coolhead_model as cm

JUNE = cm.SCENARIOS["June (hot, dry)"]
JULY = cm.SCENARIOS["July (hot, humid)"]
VERSIONS = list(cm.MODELS)


@lru_cache(maxsize=None)
def run(version, case, sc=JUNE, **overrides):
    """Cached run so tests that look at the same case share one simulation."""
    return cm.create_model(version, **overrides).run(case, sc)


# ---------------- factory and settings ----------------
def test_default_model_is_v2():
    assert cm.DEFAULT_MODEL_VERSION == "v2"
    assert isinstance(cm.create_model(), cm.ModelV2)


@pytest.mark.parametrize("version", VERSIONS)
def test_create_model_returns_requested_version(version):
    model = cm.create_model(version)
    assert model.version == version
    assert model.settings == cm.default_settings(version)


def test_unknown_version_raises():
    with pytest.raises(ValueError, match="unknown model version"):
        cm.create_model("v3")


def test_overrides_replace_single_settings():
    model = cm.create_model("v1", wind_share=0.3)
    assert model.settings.wind_share == 0.3
    assert model.settings.gap_view == cm.default_settings("v1").gap_view
    assert cm.create_model("v1").settings.wind_share == 0.5    # defaults are not changed


def test_unknown_setting_raises():
    with pytest.raises(ValueError, match="unknown settings"):
        cm.create_model("v2", windshare=0.3)


def test_explicit_settings_are_used():
    custom = dataclasses.replace(cm.default_settings("v2"), room_c=24.0)
    assert cm.create_model("v2", settings=custom).settings.room_c == 24.0


def test_v2_defaults_differ_from_v1_only_in_wet_transmittance():
    v1, v2 = dataclasses.asdict(cm.default_settings("v1")), dataclasses.asdict(cm.default_settings("v2"))
    assert {k for k in v1 if v1[k] != v2[k]} == {"wet_fabric_transmittance"}
    assert v2["wet_fabric_transmittance"] > v2["dry_fabric_transmittance"]   # wet cotton is more see-through


def test_settings_info_lists_only_settings_the_version_uses():
    v1 = {row["name"] for row in cm.settings_info("v1")}
    v2 = {row["name"] for row in cm.settings_info("v2")}
    assert {"wet_fraction", "gap_height", "flow_length"} <= v2 - v1
    assert all(row["label"] for row in cm.settings_info("v2"))


@pytest.mark.parametrize("override, message", [
    (dict(dt=120.0), "time step too long"),
    (dict(slab_nodes=2), "slab_nodes"),
    (dict(wet_fraction=1.5), "wet_fraction"),
    (dict(gap_height=0.0), "gap_height"),
])
def test_invalid_settings_raise(override, message):
    with pytest.raises(ValueError, match=message):
        cm.create_model("v2", **override)


def test_unknown_case_raises():
    with pytest.raises(ValueError, match="unknown case"):
        cm.create_model().run("green_roof", JUNE)


# ---------------- physics helpers ----------------
def test_saturation_vapour_pressure():
    assert cm.esat(0.0) == pytest.approx(611, rel=0.005)
    assert cm.esat(20.0) == pytest.approx(2339, rel=0.005)
    assert cm.esat(100.0) == pytest.approx(101325, rel=0.03)    # water boils at 100 C


def test_pressure_and_humidity_ratio():
    assert cm.pressure(0) == pytest.approx(101325)
    assert cm.pressure(184) == pytest.approx(99150, rel=0.005)
    assert cm.humidity_ratio(cm.esat(20.0), cm.pressure(0)) == pytest.approx(0.0147, rel=0.01)


def test_wind_convection():
    assert cm.h_conv(0) == 2.8
    assert cm.h_conv(2) - cm.h_conv(1) == pytest.approx(3.0)


# ---------------- weather ----------------
def test_design_day_sun_and_air_temperature():
    w = cm.design_day(JUNE)
    assert w["ghi"][0] == 0                                        # midnight
    noon = w["hr"][np.argmax(w["ghi"])]
    assert 11.5 < noon < 13.0                                       # solar noon is about 12:08
    assert 800 < w["ghi"].max() < 1100
    assert w["ta"].min() == pytest.approx(JUNE.tmin)
    assert w["ta"].max() == pytest.approx(JUNE.tmax)
    assert 13.5 <= w["hr"][np.argmax(w["ta"])] <= 15.5              # hottest mid-afternoon
    assert np.all(w["tsky"] < w["ta"] + 273.15)                     # clear sky is colder than air


def test_sun_factor_scales_sunlight():
    full, half = cm.design_day(JUNE), cm.design_day(dataclasses.replace(JUNE, sun_factor=0.5))
    np.testing.assert_allclose(half["ghi"], 0.5 * full["ghi"])


def test_design_day_cache_cannot_be_modified():
    with pytest.raises(ValueError):
        cm.design_day(JUNE)["ghi"][0] = 1.0


# ---------------- fabric (one time step) ----------------
def wet_bulb(ta, w_air, p_atm):
    """Psychrometric wet-bulb temperature: cp (ta - twb) = LV (ws(twb) - w)."""
    lo, hi = -20.0, ta
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if cm.CP_AIR * (ta - mid) - cm.LV * (cm.humidity_ratio(cm.esat(mid), p_atm) - w_air) > 0: hi = mid
        else: lo = mid
    return mid


def step(version, wet, G=0.0, ta=35.0, tsky=None, tr=None, w_air=0.008, **overrides):
    model = cm.create_model(version, **overrides)
    tsky = ta + 273.15 if tsky is None else tsky
    tr = ta if tr is None else tr
    return model.canopy_step(G, ta, tsky, tr, w_air, cm.pressure(184), 2.0, 1.0, wet,
                             model.fabric_optics(wet), model.settings.sheet_emissivity)


@pytest.mark.parametrize("version", VERSIONS)
def test_dry_fabric_in_uniform_surroundings_matches_air(version):
    tf, evap, q_roof, tg = step(version, wet=False)
    assert tf == pytest.approx(35.0, abs=1e-3)
    assert evap == 0 and q_roof == pytest.approx(0, abs=0.01) and tg == pytest.approx(35.0, abs=1e-3)


@pytest.mark.parametrize("version", VERSIONS)
def test_wet_fabric_without_sun_sits_between_wet_bulb_and_air(version):
    tf, evap, _, _ = step(version, wet=True)
    assert wet_bulb(35.0, 0.008, cm.pressure(184)) < tf < 35.0
    assert evap > 0


@pytest.mark.parametrize("version", VERSIONS)
def test_wet_fabric_is_cooler_than_dry_in_sun(version):
    sun = dict(G=900.0, tsky=280.0, tr=38.0)
    assert step(version, wet=True, **sun)[0] < step(version, wet=False, **sun)[0] - 5


def test_v2_wet_fraction_scales_evaporation():
    sun = dict(G=900.0, tsky=280.0, tr=38.0)
    full = step("v2", wet=True, **sun)[1]
    half = step("v2", wet=True, wet_fraction=0.5, **sun)[1]
    assert step("v2", wet=True, wet_fraction=0.0, **sun)[1] == 0
    assert 0 < half < full


def test_saturated_air_stops_evaporation():
    ta = 30.0
    saturated = cm.humidity_ratio(cm.esat(ta), cm.pressure(184))
    for version in VERSIONS:
        assert step(version, wet=True, ta=ta, w_air=saturated)[1] == pytest.approx(0, abs=1e-6)


# ---------------- v1 reproduces the notebook ----------------
# Printed output of coolhead_roof_model.ipynb: (peak roof C, heat in Wh/m2/day, water L/m2/day)
NOTEBOOK = {
    (JUNE, "bare"): (57.0, 1167.5, 0.0),
    (JUNE, "white"): (41.2, 528.9, 0.0),
    (JUNE, "dry_canopy"): (37.8, 544.4, 0.0),
    (JUNE, "wet_canopy"): (32.5, 299.9, 7.7),
    (JUNE, "wet_canopy_peak"): (33.7, 391.1, 4.8),
    (JUNE, "wet_canopy_fan"): (32.5, 299.9, 7.7),
    (JULY, "bare"): (57.7, 1312.9, 0.0),
    (JULY, "white"): (42.3, 688.4, 0.0),
}


@pytest.mark.parametrize("sc, case", list(NOTEBOOK))
def test_v1_matches_notebook(sc, case):
    _, s = run("v1", case, sc)
    peak, heat, water = NOTEBOOK[(sc, case)]
    assert s["peak_roof_C"] == pytest.approx(peak, abs=0.06)
    assert s["heat_in_Wh_m2_day"] == pytest.approx(heat, abs=0.06)
    assert s["water_L_m2_day"] == pytest.approx(water, abs=0.06)


# ---------------- whole-day behaviour ----------------
@pytest.mark.parametrize("version", VERSIONS)
def test_case_ranking(version):
    heat = {c: run(version, c)[1]["heat_in_Wh_m2_day"] for c in ("bare", "white", "dry_canopy", "wet_canopy")}
    assert heat["wet_canopy"] < heat["dry_canopy"] < heat["bare"]
    assert heat["white"] < heat["bare"]


@pytest.mark.parametrize("version", VERSIONS)
def test_water_use(version):
    water = {c: run(version, c)[1]["water_L_m2_day"] for c in cm.CASES}
    assert water["bare"] == water["white"] == water["dry_canopy"] == 0
    assert 0 < water["wet_canopy_peak"] < water["wet_canopy"]
    df, _ = run(version, "wet_canopy")
    assert np.all(df.evap_kg_m2s[(df.hour < 8) | (df.hour >= 19)] == 0)   # dry outside wet hours


@pytest.mark.parametrize("version", VERSIONS)
def test_humid_air_evaporates_less(version):
    humid = dataclasses.replace(JUNE, dewpoint=25.0)
    assert run(version, "wet_canopy", humid)[1]["water_L_m2_day"] < run(version, "wet_canopy")[1]["water_L_m2_day"]


@pytest.mark.parametrize("version", VERSIONS)
def test_slab_has_settled_into_daily_cycle(version):
    five = run(version, "wet_canopy")[1]["heat_in_Wh_m2_day"]
    six = run(version, "wet_canopy", spinup_days=6)[1]["heat_in_Wh_m2_day"]
    assert six == pytest.approx(five, rel=0.01)


def test_shorter_time_step_gives_same_answer():
    normal = run("v2", "wet_canopy")[1]["heat_in_Wh_m2_day"]
    fine = run("v2", "wet_canopy", dt=15.0)[1]["heat_in_Wh_m2_day"]
    assert fine == pytest.approx(normal, rel=0.01)


def test_v1_gap_air_is_outdoor_air():
    df, _ = run("v1", "wet_canopy")
    np.testing.assert_allclose(df.gap_C, df.air_C)
    assert run("v1", "bare")[0].gap_C.isna().all()


def test_v2_gap_air_is_a_mix_of_air_fabric_and_roof():
    df, _ = run("v2", "wet_canopy")
    parts = df[["air_C", "fabric_C", "roof_C"]]
    assert np.all(df.gap_C >= parts.min(axis=1) - 1e-9)
    assert np.all(df.gap_C <= parts.max(axis=1) + 1e-9)
    assert (df.gap_C < df.air_C - 0.1).any()                      # the wet fabric cools the gap


def test_v2_is_less_optimistic_than_v1_for_wet_canopy():
    assert run("v2", "wet_canopy")[1]["heat_in_Wh_m2_day"] > run("v1", "wet_canopy")[1]["heat_in_Wh_m2_day"]


def test_run_all_table():
    table = cm.create_model("v1").run_all(JUNE, cases=("bare", "white"))
    assert list(table.case) == ["bare", "white"]
    assert table.heat_cut_vs_bare_pct.iloc[0] == 0
    assert table.heat_cut_vs_bare_pct.iloc[1] == pytest.approx(54.7, abs=0.06)
    assert (table.model == "v1").all()
