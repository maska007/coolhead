"""CoolHead roof heat model, shared by the notebook and the app.

Estimates how hot a flat concrete roof gets, and how much heat flows into the room below, with and
without the CoolHead canopy, step by step (every 30 s) through a clear-sky design day. The day is
repeated (``spinup_days``) until the slab settles into a daily cycle. More detail and web links are
in ``model_readme.md``.

Two model versions live here:

* ``v1`` - the original notebook model (``coolhead_roof_model.ipynb``), unchanged physics.
* ``v2`` - v1 plus the fixes from ``initial_findings.md`` (see "Version 2 changes" below).

Usage::

    import coolhead_model as cm
    model = cm.create_model()                      # DEFAULT_MODEL_VERSION ("v2")
    model = cm.create_model("v1", wind_share=0.4)  # override any Settings field
    df, summary = model.run("wet_canopy", cm.SCENARIOS["June (hot, dry)"])
    table = model.run_all(cm.SCENARIOS["June (hot, dry)"])

Formulas and coefficients
-------------------------
Weather (``design_day``)
    Sun: clear-sky global horizontal irradiance (GHI) from the Ineichen-Perez model (2002) in pvlib,
    with pvlib's monthly Linke turbidity (haze) for the site, times ``sun_factor``. A flat roof
    receives GHI directly.
    Air temperature: ASHRAE design-day profile, T(h) = Tmax - f(h) (Tmax - Tmin), where f(h) is the
    ASHRAE hourly fraction of the daily range (ASHRAE Handbook - Fundamentals, ch. 14). Coolest
    about 05:00, hottest about 14:00-15:00.
    Sky temperature: Berdahl-Martin (1984) clear-sky emissivity
    eps_sky = 0.711 + 0.56 (Td/100) + 0.73 (Td/100)^2 (Td = dew point, C), Tsky = eps_sky^(1/4) Ta
    (kelvin). Drier air -> colder sky -> more cooling by radiation.

Humidity
    Saturation vapour pressure, Magnus formula with Alduchov-Eskridge (1996) coefficients:
    e_s(T) = 610.94 exp(17.625 T / (T + 243.04)) Pa, T in C.
    Humidity ratio (kg water per kg dry air): W = 0.622 e / (p - e).
    Air pressure at the site altitude z (standard atmosphere): p = 101325 (1 - 2.25577e-5 z)^5.25588.

Long-wave (thermal) radiation
    Stefan-Boltzmann law: q = eps sigma (T1^4 - T2^4), sigma = 5.670e-8 W/m2K4.
    Roof and canopy are treated as two large parallel grey plates, with exchange factor
    F = 1 / (1/e1 + 1/e2 - 1). ``gap_view`` is the share of the roof's view taken up by the canopy.

Wind convection (``h_conv``)
    h = 2.8 + 3.0 v W/m2K (Watmuff, Charters and Proctor 1977), v = wind speed in m/s. This is
    McAdams' 5.7 + 3.8 v with the radiation part removed, which is right here because radiation is
    modelled separately. Air speed in the gap is ``wind_share`` x wind.

Evaporation from wet fabric (Lewis relation)
    Heat and water vapour move through the thin air layer at a surface in the same way, so the
    mass transfer coefficient follows from the heat transfer coefficient: g = h / cp (kg/m2s),
    taking the Lewis number of air-water vapour as 1 (it is about 0.85, so this slightly
    underestimates evaporation). Evaporation rate E = g (W_s(T_fabric) - W_air) kg/m2s, never
    negative (no condensation). Each kg evaporated takes LV = 2.43 MJ of heat from the fabric
    (latent heat of water at about 30 C). cp = 1006 J/kgK for dry air.

Fabric
    Thin sheet with no heat storage. Each step its temperature solves the energy balance
    (sun absorbed + long-wave radiation + convection - evaporation = 0) by bisection; the balance
    falls steadily as fabric temperature rises, so there is exactly one answer. Optical properties
    (solar absorptance, solar transmittance, emissivity) differ for dry and wet fabric.

Roof slab
    1-D heat conduction, dT/dt = alpha d2T/dx2 with alpha = k / (rho c), solved with explicit
    finite differences (FTCS) on ``slab_nodes`` layers; the two surface nodes hold half a layer.
    Stable when the Fourier number alpha dt / dx^2 <= 0.5 (checked against 0.4 for headroom at the
    surfaces). Ceiling to room: q_in = h_in (T_ceiling - T_room), h_in = 6.1 W/m2K (ASHRAE surface
    coefficient for a horizontal surface with heat flowing down, including radiation).

Version 2 changes
-----------------
1. Wet fabric solar transmittance 0.08 -> 0.20 (dry stays 0.10).
   Why: water fills the gaps between cotton fibres so they scatter less light, and wet cotton lets
   more through (Osterwalder et al. 2000: bleached cotton UV transmittance about 30 % dry, 50 %
   wet). v1 had the direction backwards. 0.20 is an estimate; measure it with the experiment in
   ``experiment_transp.md``.
2. Wetness factor ``wet_fraction`` multiplies the evaporation rate (default 1.0).
   Why: v1 treats the cloth as a perfectly wet water surface, which is the upper limit. Real cloth
   has drier patches. Set it from the cloth-weighing experiment (``experiment_evap.md``).
3. The roof's open sides (1 - ``gap_view``) radiate to the surroundings at air temperature.
   Why: looking out sideways from under a canopy you see walls and horizon, not the cold sky. v1
   was also inconsistent: the fabric underside already used air temperature for the same view.
4. Gap air is its own node (well mixed). Air flows through at
   m = rho v_gap ``gap_height`` / ``flow_length`` kg/s per m2 of roof, with rho = p / (R T).
   Heat balance:   m cp (T_gap - Ta) = h_gap (T_fabric - T_gap) + h_gap (T_roof - T_gap)
   Vapour balance: m (W_gap - W_air) = g_gap (W_s(T_fabric) - W_gap)
   Why: v1 assumed outdoor air in the gap. That makes underside evaporation too high (the gap air
   really gets more humid) and gap air too warm (it is really cooled by the wet cloth and the cool
   roof). The v1 conclusions about wind and the fan depend on this assumption.

Effect on the June heat cut for the wet canopy vs bare concrete: v1 74 %; fix 1 alone 61 %; fix 3
alone 66 %; fix 4 alone 76 %; all of v2 54 % (fix 2 has no effect at its default of 1.0).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd
import pvlib

SIGMA, CP_AIR, LV = 5.670e-8, 1006.0, 2.43e6   # W/m2K4, J/kgK, J/kg
R_AIR = 287.05                                  # J/kgK, gas constant of dry air
# ASHRAE fraction of the daily temperature range below the maximum, for hours 1..24
ASHRAE_FRAC = (0.88, 0.92, 0.95, 0.98, 1.00, 0.98, 0.91, 0.74, 0.55, 0.38, 0.23, 0.13,
               0.05, 0.00, 0.00, 0.06, 0.14, 0.24, 0.39, 0.50, 0.59, 0.68, 0.75, 0.82)


# ---------------- weather inputs ----------------
@dataclass(frozen=True)
class Site:
    name: str
    lat: float
    lon: float
    alt: float      # m above sea level
    tz: str


FAISALABAD = Site("Faisalabad", lat=31.42, lon=73.08, alt=184, tz="Asia/Karachi")


@dataclass(frozen=True)
class Scenario:
    """One design day: what the weather is doing (these become the app's main sliders)."""
    date: str
    tmax: float               # C, daily maximum air temperature
    tmin: float               # C, daily minimum air temperature
    dewpoint: float           # C, sets humidity and sky temperature
    wind: float = 2.0         # m/s at roof level
    sun_factor: float = 1.0   # share of clear-sky sunlight (1 = cloudless, 0.5 = hazy/cloudy)
    site: Site = FAISALABAD


# Climate averages 1980-2015 (Wikipedia climate table for Faisalabad): June max 40.3 / min 26.7 C,
# July max 37.3 / min 27.3 C. Average RH: June 18 %, July 63 %, which imply dew points of roughly
# 6-11 C in June and about 24 C in July. We use 10 C (dry, pre-monsoon) and 25 C (monsoon).
SCENARIOS = {
    "June (hot, dry)":   Scenario("2026-06-15", tmax=40.3, tmin=26.7, dewpoint=10.0),
    "July (hot, humid)": Scenario("2026-07-20", tmax=37.3, tmin=27.3, dewpoint=25.0),
}

CASES = {"bare": "Bare concrete", "white": "White paint", "dry_canopy": "Dry canopy (shade only)",
         "wet_canopy": "CoolHead wet 08-19 h", "wet_canopy_peak": "CoolHead wet 11-17 h",
         "wet_canopy_fan": "CoolHead wet + fan"}


# ---------------- model settings (the app's hidden settings section) ----------------
def _setting(default, label, unit="", versions=("v1", "v2")):
    return field(default=default, metadata=dict(label=label, unit=unit, versions=versions))


@dataclass(frozen=True)
class Settings:
    """Every model assumption. Defaults are the v1 (notebook) values; see default_settings()."""
    room_c: float = _setting(26.0, "Indoor air temperature (AC set point)", "C")
    h_in: float = _setting(6.1, "Ceiling-to-room heat transfer (ASHRAE, heat flowing down)", "W/m2K")
    # reinforced concrete roof slab
    slab_thick: float = _setting(0.15, "Slab thickness", "m")
    slab_k: float = _setting(1.6, "Slab conductivity", "W/mK")
    slab_rho: float = _setting(2400.0, "Slab density", "kg/m3")
    slab_c: float = _setting(880.0, "Slab specific heat", "J/kgK")
    slab_nodes: int = _setting(15, "Slab layers in the calculation")
    # roof surfaces: solar absorptance, thermal emissivity
    bare_absorptance: float = _setting(0.70, "Bare concrete: solar absorptance")
    bare_emissivity: float = _setting(0.90, "Bare concrete: emissivity")
    white_absorptance: float = _setting(0.30, "White paint: solar absorptance")
    white_emissivity: float = _setting(0.90, "White paint: emissivity")
    sheet_absorptance: float = _setting(0.65, "Sheet under canopy: solar absorptance")
    sheet_emissivity: float = _setting(0.90, "Sheet under canopy: emissivity")
    # white cotton canopy
    dry_fabric_absorptance: float = _setting(0.35, "Dry fabric: solar absorptance")
    dry_fabric_transmittance: float = _setting(0.10, "Dry fabric: solar transmittance")
    dry_fabric_emissivity: float = _setting(0.88, "Dry fabric: emissivity")
    wet_fabric_absorptance: float = _setting(0.45, "Wet fabric: solar absorptance")
    wet_fabric_transmittance: float = _setting(0.08, "Wet fabric: solar transmittance")
    wet_fabric_emissivity: float = _setting(0.95, "Wet fabric: emissivity")
    # gap between roof and canopy
    gap_view: float = _setting(0.85, "Share of the roof's view taken up by the canopy")
    wind_share: float = _setting(0.5, "Wind speed in the gap as a share of the open wind")
    fan_speed: float = _setting(1.5, "Air speed in the gap when the stage-2 fan runs", "m/s")
    # water schedule
    wet_start: float = _setting(8.0, "Fabric kept wet from", "h")
    wet_end: float = _setting(19.0, "Fabric kept wet until", "h")
    peak_start: float = _setting(11.0, "Water-saving schedule: wet from", "h")
    peak_end: float = _setting(17.0, "Water-saving schedule: wet until", "h")
    # v2 only
    wet_fraction: float = _setting(1.0, "Wetness factor (1 = perfectly wet; measure it)",
                                   versions=("v2",))
    gap_height: float = _setting(0.5, "Height of the gap under the canopy", "m", versions=("v2",))
    flow_length: float = _setting(6.0, "Distance air travels under the canopy", "m",
                                  versions=("v2",))
    # numerics
    dt: float = _setting(30.0, "Time step", "s")
    spinup_days: int = _setting(5, "Days repeated until the slab settles")


def default_settings(version=None):
    """Default Settings for a model version (DEFAULT_MODEL_VERSION when None)."""
    version = version or DEFAULT_MODEL_VERSION
    _check_version(version)
    if version == "v1":
        return Settings()
    return Settings(wet_fabric_transmittance=0.20)


def settings_info(version=None):
    """Rows describing each setting used by a version (name, label, unit, default) for the UI."""
    version = version or DEFAULT_MODEL_VERSION
    s = default_settings(version)
    return [dict(name=f.name, label=f.metadata["label"], unit=f.metadata["unit"],
                 default=getattr(s, f.name))
            for f in dataclasses.fields(Settings) if version in f.metadata["versions"]]


# ---------------- physics helpers ----------------
def esat(t):
    """Saturation vapour pressure, Pa (Magnus formula), t in C."""
    return 610.94 * np.exp(17.625 * t / (t + 243.04))


def pressure(alt):
    """Standard atmospheric pressure at an altitude, Pa."""
    return 101325.0 * (1 - 2.25577e-5 * alt) ** 5.25588


def humidity_ratio(p_v, p_atm):
    """kg water per kg dry air."""
    return 0.622 * p_v / (p_atm - p_v)


def h_conv(v):
    """W/m2K, wind convection without radiation (Watmuff et al. 1977);
    radiation is modelled separately, so it must not be counted twice."""
    return 2.8 + 3.0 * v


def radiation_factor(e1, e2):
    """Exchange factor between two large parallel grey surfaces."""
    return 1.0 / (1 / e1 + 1 / e2 - 1)


@lru_cache(maxsize=32)
def design_day(sc: Scenario, dt: float = 30.0):
    """Hourly weather for one day at time step dt: sun, air and sky temperature, humidity.

    Air temperature follows the ASHRAE daily profile between tmin and tmax. Sunlight is the
    Ineichen clear-sky value scaled by sun_factor. Sky temperature is from Berdahl-Martin.
    """
    site = sc.site
    loc = pvlib.location.Location(site.lat, site.lon, tz=site.tz, altitude=site.alt)
    t = pd.date_range(sc.date, periods=int(86400 / dt), freq=f"{int(dt)}s", tz=site.tz)
    ghi = loc.get_clearsky(t, model="ineichen")["ghi"].clip(lower=0).to_numpy() * sc.sun_factor
    hr = (t.hour + t.minute / 60 + t.second / 3600).to_numpy()
    frac_pts = np.array((ASHRAE_FRAC[-1],) + ASHRAE_FRAC)        # hour 0 .. 24
    frac = np.interp(hr, np.arange(25), frac_pts)
    ta = sc.tmax - (sc.tmax - sc.tmin) * frac
    td = sc.dewpoint
    eps_sky = 0.711 + 0.56 * (td / 100) + 0.73 * (td / 100) ** 2
    tsky = (eps_sky ** 0.25) * (ta + 273.15)                     # K
    p_atm = pressure(site.alt)
    w = dict(hr=hr, ghi=ghi, ta=ta, tsky=tsky, rh=100 * esat(td) / esat(ta))
    for a in w.values():
        a.flags.writeable = False                                # cached: callers must not edit
    w.update(w_air=humidity_ratio(esat(td), p_atm), p_atm=p_atm)
    return w


def _bisect(net, lo, hi, tol=1e-4):
    """Root of a decreasing function net(x) between lo and hi."""
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if net(mid) > 0: lo = mid
        else: hi = mid
    return 0.5 * (lo + hi)


# ---------------- models ----------------
class RoofModel:
    """Shared time stepping: slab conduction, roof surfaces, schedules. Subclasses add the canopy."""
    version = ""
    description = ""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._validate()

    def __repr__(self):
        return f"{type(self).__name__}(version={self.version!r})"

    def _validate(self):
        s = self.settings
        if s.slab_nodes < 3:
            raise ValueError("slab_nodes must be at least 3")
        dx = s.slab_thick / (s.slab_nodes - 1)
        fourier = s.slab_k / (s.slab_rho * s.slab_c) * s.dt / dx ** 2
        # explicit scheme needs Fourier <= 0.5; 0.4 leaves headroom for the surface nodes
        if fourier > 0.4:
            raise ValueError(f"time step too long for this slab (Fourier number {fourier:.2f} > 0.4): "
                             "lower dt or use fewer slab_nodes")
        if not 0 <= s.wet_fraction <= 1:
            raise ValueError("wet_fraction must be between 0 and 1")
        if s.gap_height <= 0 or s.flow_length <= 0:
            raise ValueError("gap_height and flow_length must be positive")

    def surface(self, case):
        s = self.settings
        name = "sheet" if "canopy" in case else case
        return getattr(s, f"{name}_absorptance"), getattr(s, f"{name}_emissivity")

    def fabric_optics(self, wet):
        s = self.settings
        p = "wet" if wet else "dry"
        return (getattr(s, f"{p}_fabric_absorptance"), getattr(s, f"{p}_fabric_transmittance"),
                getattr(s, f"{p}_fabric_emissivity"))

    def canopy_step(self, G, ta, tsky_k, tr, w_air, p_atm, wind, v_gap, wet, optics, e_r):
        """Solve the canopy for one time step.

        Returns (fabric_C, evaporation_kg_m2s, heat_into_roof_surface_Wm2, gap_air_C).
        """
        raise NotImplementedError

    def run(self, case, sc: Scenario):
        """Simulate one case for one scenario. Returns (hourly DataFrame, summary dict)."""
        if case not in CASES:
            raise ValueError(f"unknown case {case!r}; choose from {list(CASES)}")
        s = self.settings
        w = design_day(sc, s.dt)
        n = s.slab_nodes; dx = s.slab_thick / (n - 1)
        alpha = s.slab_k / (s.slab_rho * s.slab_c)
        cap_half = s.slab_rho * s.slab_c * dx / 2
        T = np.full(n, (sc.tmax + sc.tmin) / 2)
        canopy = "canopy" in case
        a_r, e_r = self.surface(case)
        hours = (s.peak_start, s.peak_end) if case == "wet_canopy_peak" else (s.wet_start, s.wet_end)
        steps = len(w["hr"])
        rec = {k: np.zeros(steps) for k in ("roof", "ceiling", "q_in", "fabric", "gap", "evap", "fan")}
        for day in range(s.spinup_days):
            for i in range(steps):
                G, ta, tsky, hr = w["ghi"][i], w["ta"][i], w["tsky"][i], w["hr"][i]
                tr = T[0]; trk = tr + 273.15
                if not canopy:
                    q = a_r * G + e_r * SIGMA * (tsky ** 4 - trk ** 4) + h_conv(sc.wind) * (ta - tr)
                    tf, tg, evap, fan = np.nan, np.nan, 0.0, False
                else:
                    wet = case != "dry_canopy" and hours[0] <= hr < hours[1]
                    v_gap = s.wind_share * sc.wind
                    fan = case == "wet_canopy_fan" and wet and sc.wind < 1.0 and tr > ta + 0.5
                    if fan: v_gap = max(v_gap, s.fan_speed)
                    tf, evap, q, tg = self.canopy_step(G, ta, tsky, tr, w["w_air"], w["p_atm"],
                                                       sc.wind, v_gap, wet, self.fabric_optics(wet), e_r)
                # conduction through the slab (explicit finite differences)
                Tn = T.copy()
                Tn[0] = T[0] + s.dt / cap_half * (q + s.slab_k * (T[1] - T[0]) / dx)
                Tn[1:-1] = T[1:-1] + alpha * s.dt / dx ** 2 * (T[:-2] - 2 * T[1:-1] + T[2:])
                q_in = s.h_in * (T[-1] - s.room_c)
                Tn[-1] = T[-1] + s.dt / cap_half * (s.slab_k * (T[-2] - T[-1]) / dx - q_in)
                T = Tn
                if day == s.spinup_days - 1:
                    rec["roof"][i], rec["ceiling"][i], rec["q_in"][i] = T[0], T[-1], q_in
                    rec["fabric"][i], rec["gap"][i], rec["evap"][i], rec["fan"][i] = tf, tg, evap, fan
        df = pd.DataFrame({"hour": w["hr"], "air_C": w["ta"], "sun_Wm2": w["ghi"], "rh_pct": w["rh"],
                           "roof_C": rec["roof"], "ceiling_C": rec["ceiling"],
                           "heat_in_Wm2": rec["q_in"], "fabric_C": rec["fabric"], "gap_C": rec["gap"],
                           "evap_kg_m2s": rec["evap"], "fan_on": rec["fan"].astype(bool)})
        summary = dict(case=case, model=self.version,
                       peak_roof_C=df.roof_C.max(), peak_fabric_C=df.fabric_C.max(),
                       mean_roof_C=df.roof_C.mean(), peak_ceiling_C=df.ceiling_C.max(),
                       heat_in_Wh_m2_day=df.heat_in_Wm2.clip(lower=0).sum() * s.dt / 3600,
                       peak_heat_in_Wm2=df.heat_in_Wm2.max(),
                       water_L_m2_day=df.evap_kg_m2s.sum() * s.dt,
                       fan_hours=df.fan_on.sum() * s.dt / 3600)
        return df, summary

    def run_all(self, sc: Scenario, cases=tuple(CASES)):
        """Summary table for several cases, with % heat cut compared with the bare roof."""
        rows = []
        for case in cases:
            _, summ = self.run(case, sc)
            rows.append(dict(summ, label=CASES[case]))
        table = pd.DataFrame(rows)
        base = self.run("bare", sc)[1] if "bare" not in cases else rows[list(cases).index("bare")]
        table["heat_cut_vs_bare_pct"] = 100 * (1 - table.heat_in_Wh_m2_day / base["heat_in_Wh_m2_day"])
        return table


class ModelV1(RoofModel):
    """The original notebook model: gap air is outdoor air, open sides see the sky."""
    version = "v1"
    description = "Original notebook model"

    def canopy_step(self, G, ta, tsky_k, tr, w_air, p_atm, wind, v_gap, wet, optics, e_r):
        s = self.settings
        a_f, tau_f, e_f = optics
        h_top, h_bot = h_conv(wind), h_conv(v_gap)
        fr = radiation_factor(e_f, e_r)
        trk, tak = tr + 273.15, ta + 273.15

        def balance(tf):
            tfk = tf + 273.15
            q = a_f * G
            q += e_f * SIGMA * (tsky_k ** 4 - tfk ** 4)                    # top side to sky
            q += s.gap_view * fr * SIGMA * (trk ** 4 - tfk ** 4)           # underside to roof
            q += (1 - s.gap_view) * e_f * SIGMA * (tak ** 4 - tfk ** 4)    # underside to surroundings
            q += (h_top + h_bot) * (ta - tf)
            evap = 0.0
            if wet:
                dw = max(humidity_ratio(esat(tf), p_atm) - w_air, 0.0)
                evap = (h_top + h_bot) / CP_AIR * dw                       # kg/m2s (Lewis relation)
                q -= evap * LV
            return q, evap

        tf = _bisect(lambda x: balance(x)[0], ta - 40, ta + 60)
        evap = balance(tf)[1]
        tfk = tf + 273.15
        q = self._sheet_absorbed(G, tau_f)
        q += s.gap_view * fr * SIGMA * (tfk ** 4 - trk ** 4)
        q += (1 - s.gap_view) * e_r * SIGMA * (tsky_k ** 4 - trk ** 4)        # open sides see the sky
        q += h_bot * (ta - tr)
        return tf, evap, q, ta

    def _sheet_absorbed(self, G, tau_f):
        return self.settings.sheet_absorptance * tau_f * G


class ModelV2(ModelV1):
    """v1 with the fixes from initial_findings.md (see the module docstring)."""
    version = "v2"
    description = "Improved model (fixes from initial_findings.md)"

    def canopy_step(self, G, ta, tsky_k, tr, w_air, p_atm, wind, v_gap, wet, optics, e_r):
        s = self.settings
        a_f, tau_f, e_f = optics
        h_top, h_bot = h_conv(wind), h_conv(v_gap)
        fr = radiation_factor(e_f, e_r)
        trk, tak = tr + 273.15, ta + 273.15
        # air flowing through the gap, per m2 of roof (kg/m2s): density * speed * height / length
        m_air = p_atm / (R_AIR * tak) * v_gap * s.gap_height / s.flow_length
        f_wet = s.wet_fraction if wet else 0.0

        def state(tf):
            """Gap air temperature and humidity, and evaporation from both sides, for fabric at tf."""
            # well-mixed gap: air in at ta, warmed or cooled by the fabric underside and the roof
            tg = (m_air * CP_AIR * ta + h_bot * (tf + tr)) / (m_air * CP_AIR + 2 * h_bot)
            evap_top = evap_bot = 0.0
            w_gap = w_air
            if f_wet > 0:
                ws = humidity_ratio(esat(tf), p_atm)
                if ws > w_air:
                    g_top, g_bot = f_wet * h_top / CP_AIR, f_wet * h_bot / CP_AIR   # Lewis relation
                    w_gap = (m_air * w_air + g_bot * ws) / (m_air + g_bot)          # vapour balance
                    evap_top, evap_bot = g_top * (ws - w_air), g_bot * (ws - w_gap)
            return tg, evap_top + evap_bot

        def net(tf):
            tfk = tf + 273.15
            tg, evap = state(tf)
            q = a_f * G
            q += e_f * SIGMA * (tsky_k ** 4 - tfk ** 4)                    # top side to sky
            q += s.gap_view * fr * SIGMA * (trk ** 4 - tfk ** 4)           # underside to roof
            q += (1 - s.gap_view) * e_f * SIGMA * (tak ** 4 - tfk ** 4)    # underside to surroundings
            q += h_top * (ta - tf) + h_bot * (tg - tf)
            return q - evap * LV

        tf = _bisect(net, ta - 40, ta + 60)
        tg, evap = state(tf)
        tfk = tf + 273.15
        q = self._sheet_absorbed(G, tau_f)
        q += s.gap_view * fr * SIGMA * (tfk ** 4 - trk ** 4)
        q += (1 - s.gap_view) * e_r * SIGMA * (tak ** 4 - trk ** 4)          # open sides see surroundings
        q += h_bot * (tg - tr)
        return tf, evap, q, tg


# ---------------- factory ----------------
MODELS = {"v1": ModelV1, "v2": ModelV2}
DEFAULT_MODEL_VERSION = "v2"


def _check_version(version):
    if version not in MODELS:
        raise ValueError(f"unknown model version {version!r}; choose from {list(MODELS)}")


def create_model(version=None, settings: Settings | None = None, **overrides) -> RoofModel:
    """Build a model. version defaults to DEFAULT_MODEL_VERSION; settings default to that version's
    defaults; keyword overrides replace single Settings fields, e.g. create_model("v2", wet_fraction=0.8)."""
    version = version or DEFAULT_MODEL_VERSION
    _check_version(version)
    settings = settings or default_settings(version)
    unknown = set(overrides) - {f.name for f in dataclasses.fields(Settings)}
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    return MODELS[version](dataclasses.replace(settings, **overrides))
