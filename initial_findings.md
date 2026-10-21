# CoolHead roof model: initial review findings

Review of `coolhead_roof_model.ipynb`, 2026-10-21. It covers the cloth evaporation formula, the sun
and wind inputs, and the overall numerics.

**Verdict:** the core physics is sound. The evaporation formula, the sun input and the wind formula
are all standard, textbook approaches, and the units and numbers pass sanity checks. A few assumptions
should be fixed or stated openly. Most of them currently make CoolHead look slightly better than it
would in reality.

---

## 1. Evaporation from the cloth (cell 7, `fabric_temp`)

```python
evap = (h_top + h_bot) / CP_AIR * dw        # kg/m²s (Lewis relation)
```

**Correct.** This is the Lewis relation: how fast heat moves from air to a surface (`h`) tells you how
fast water vapour moves away from it. The units work out to kg/m²/s. `dw` uses the saturated humidity
at the *fabric's own temperature*, which is right. The energy balance holds together: the fabric
temperature settles somewhere between the wet-bulb temperature and the air temperature.

**There is no cloth-specific coefficient.** The model treats the fabric as a perfectly wet water
surface on both sides whenever it is being wetted. That gives the *maximum possible* evaporation. Real
cotton gets partly dry patches, the water supply may not keep up, and the underside may be less wet
than the top.

- Add a **wetness factor** `f_wet` (about 0.6–0.9) multiplying `evap`. State that 1.0 is the ideal
  limit.
- **Measure it.** Weigh a wet cloth sample in the sun every 10–15 minutes. The weight lost is the real
  evaporation rate. Compare it with the model's `water_L_m2_h` and adjust `f_wet` until they match.
- Smaller points:
  - The Lewis number for air and water is about 0.85, not exactly 1. With 1, the formula
    *underestimates* evaporation by about 10%, which errs on the safe side.
  - `LV` is fixed at its 30 °C value, which is fine.

**Gap air is assumed to be outdoor air** (temperature `ta`, humidity `w_air`), even though the cloth's
underside evaporates into it. With little airflow in the gap:
- the gap air becomes more humid, so the underside evaporates less than modelled (too optimistic);
- the gap air is cooled by the wet cloth and the cool roof, so it heats the roof less than modelled
  (too pessimistic).

These two errors partly cancel, but this is the biggest simplification in the model (see section 4).

## 2. Sun (cell 5 and `FABRIC` settings)

- **Clear-sky GHI from pvlib Ineichen:** correct. GHI is the right input for a flat roof, and a
  cloudless "worst case" day is a sensible design choice.
- **Berdahl–Martin sky emissivity:** formula and coefficients are correct (dew point in °C). Strictly
  it is a night-time formula. Its small daytime correction is skipped, which is acceptable.
- **ASHRAE daily temperature profile:** values and hour indexing are correct.
- ⚠️ **Wet fabric transmittance is backwards.** `FABRIC["wet"]` sets transmittance to **0.08**, lower
  than the dry value of 0.10. Wet cotton actually lets *more* light through: water fills the gaps
  between fibres so they scatter less. This is the well-known reason a wet T-shirt protects less
  against UV. A wet value of about 0.15–0.25 is more realistic. Wet cloth absorbing more (0.45 vs 0.35)
  is correct. **This error flatters CoolHead.**
- **Inconsistency in radiation to the open sides:** in `run`, the roof's uncovered 15% of view
  (`1 - GAP_VIEW`) radiates to the **cold sky**. In `fabric_temp`, the fabric's underside radiates to
  the **surroundings at air temperature**. Looking out sideways from under a canopy you mostly see
  walls and horizon, so the roof should also use `ta`. **This error is also slightly in CoolHead's
  favour.**

## 3. Wind (`h_conv = 2.8 + 3.0·v`)

- **Correct**, as long as radiation is modelled separately, which it is. Watmuff et al. (1977) is
  McAdams' formula with the radiation part removed, so the code comment is right.
- It is a low-to-mid estimate. Building-roof correlations such as Sharples & Charlesworth (about
  6.5 + 3.3·v) give higher values. Say on the slides that this is a conservative choice.
- `GAP_WIND_SHARE = 0.5` (gap air speed = half the open wind) is a guess. That is fine if it is called
  one. A flat-plate formula used for flow in a channel is only approximate.
- `v` should be the wind speed *at roof level*. Weather station data is measured at 10 m and is usually
  higher.

## 4. The wind test and the stage-2 fan (cell 11)

The result that more wind lets in more heat and that the fan never turns on is mathematically
consistent with the model. The fan's rule (`tr > ta + 0.5`) can never be met, because a wet-shaded
roof is always cooler than the air.

However, that conclusion comes **entirely from the assumption that gap air stays at outdoor
temperature** (section 1). If the gap air is cooled by the wet cloth, more airflow might help instead.
Options:

- model the gap air as its own temperature/humidity node, or
- describe the wind/fan result as uncertain on the slide.

The wind test also only runs the wet canopy. Add the bare roof as well, to see whether the
*percentage* benefit changes with wind (wind cools a bare roof too).

## 5. Things checked and found fine

- **Slab numerical stability:** the step-size number (Fourier number) is about 0.2, under the 0.5
  limit for the explicit scheme. The surface nodes (Biot ≈ 0.1) are stable too.
- **Spin-up:** 5 days is enough. 15 cm of concrete responds over about 8 hours.
- **Bisection solver:** the energy balance always decreases as the fabric gets hotter, so the solver
  can only land on one answer. The search bracket (`ta − 40` to `ta + 60`) is wide enough.
- **Water use:** 7.7 L/m²/day in June matches a rough hand estimate (sun absorbed by the cloth plus
  heat from hot dry air). It is also close to typical June pan evaporation in Punjab.

---

## Recommended fixes, ranked by importance

1. **Raise the wet fabric transmittance** in `FABRIC["wet"]` from 0.08 to about 0.15–0.25.
2. **Add a wetness factor `f_wet`** to the evaporation term. Measure it with the cloth-weighing
   experiment and calibrate the model to the measurement.
3. **Make the roof's open-side radiation use `ta`** instead of the sky temperature, to match the fabric
   side.
4. **Address the gap-air assumption** before drawing conclusions about wind and the fan: either model
   gap air temperature and humidity, or label the result as uncertain.
5. *(Nice to have)* Add the bare roof to the wind test. Note the conservative choice of convection
   formula and that the wind speed is at roof level.

All of these mostly make CoolHead look a little less good. Making these fixes before a judge points
them out makes the project more convincing.
