# CoolHead roof model: how it works

The model lives in `coolhead_model.py`. It estimates how hot a flat concrete roof gets, and how much
heat flows through the ceiling into the room below, with and without the CoolHead canopy.

It steps through one clear-sky design day every 30 seconds. The day is repeated (5 times by default)
until the concrete slab settles into a regular daily cycle, and the last day is reported.

These are **modelled** results built from published physics and stated assumptions, not
measurements. Every assumption is a named setting that can be changed (see
[All settings](#all-settings)).

## Contents

- [Using the model](#using-the-model)
- [Cases compared](#cases-compared)
- [Formulas and coefficients](#formulas-and-coefficients)
- [Version 2 changes and why](#version-2-changes-and-why)
- [All settings](#all-settings)
- [Known limitations](#known-limitations)
- [References](#references)

## Using the model

```python
import coolhead_model as cm

model = cm.create_model()                      # the default version, cm.DEFAULT_MODEL_VERSION ("v2")
model = cm.create_model("v1")                  # the original notebook model
model = cm.create_model("v2", wet_fraction=0.8, wind_share=0.4)   # change any setting by name

june = cm.SCENARIOS["June (hot, dry)"]
df, summary = model.run("wet_canopy", june)    # hourly table + one-line summary
table = model.run_all(june)                    # all cases, with % heat cut vs bare roof

windy = cm.Scenario("2026-06-15", tmax=40.3, tmin=26.7, dewpoint=10.0, wind=4.0, sun_factor=0.8)
```

`cm.settings_info("v2")` lists every setting the version uses, with its label, unit and default.

## Cases compared

| Case | What it is |
|---|---|
| `bare` | Bare weathered concrete roof |
| `white` | White-painted roof (the cheap alternative) |
| `dry_canopy` | White canopy, never wetted (shade only) |
| `wet_canopy` | CoolHead canopy kept wet 08:00–19:00, natural breeze only (stage 1) |
| `wet_canopy_peak` | Canopy wet only 11:00–17:00 (water-saving schedule) |
| `wet_canopy_fan` | Wet canopy + backup fan in the gap when the air is calm (stage 2) |

## Formulas and coefficients

### Sun

Sunlight is the **clear-sky global horizontal irradiance (GHI)**: all the sunlight, direct and
scattered, falling on a flat surface under a cloudless sky. It comes from the **Ineichen–Perez
model** as implemented in [pvlib](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.ineichen.html).
That model accounts for the sun's position (date, time, latitude, longitude) and for haze, using
pvlib's monthly *Linke turbidity* values for the site. The result is multiplied by `sun_factor`
(1 = cloudless; lower for haze or cloud). A flat roof receives GHI directly, so no tilt correction is
needed.

### Air temperature through the day

The standard **ASHRAE design-day profile**:

$$T(h) = T_{max} - f(h)\,(T_{max} - T_{min})$$

where $f(h)$ is ASHRAE's hourly *fraction of the daily temperature range* (ASHRAE Handbook –
Fundamentals, ch. 14). It is 1.00 at about 05:00 (coolest) and 0.00 at 14:00–15:00 (hottest). Values
in between are interpolated linearly to the 30-second time step.

### Sky temperature

The sky is much colder than the air, especially when the air is dry, so roofs lose heat to it by
radiation. The **Berdahl–Martin (1984)** clear-sky emissivity is:

$$\varepsilon_{sky} = 0.711 + 0.56\,\frac{T_d}{100} + 0.73\left(\frac{T_d}{100}\right)^2 \qquad T_{sky} = \varepsilon_{sky}^{1/4}\,T_a$$

with $T_d$ the dew point in °C, and $T_a$ and $T_{sky}$ in kelvin. Drier air means a colder sky and
more cooling by radiation. Strictly, this is a night-time fit; its small daytime correction is not
applied.

### Humidity

- **Saturation vapour pressure**, the most water vapour air can hold at temperature *T* (°C), is
  given by the
  [Magnus formula](https://en.wikipedia.org/wiki/Clausius%E2%80%93Clapeyron_relation#Meteorology_and_climatology)
  with the Alduchov–Eskridge (1996) coefficients:
  $$e_s(T) = 610.94\,\exp\!\left(\frac{17.625\,T}{T + 243.04}\right)\ \text{Pa}$$
- The **[humidity ratio](https://en.wikipedia.org/wiki/Mixing_ratio)** is kg of water vapour per kg
  of dry air. The 0.622 is the ratio of the molar masses of water and air:
  $$W = 0.622\,\frac{e}{p - e}$$
- **Air pressure** at the site's altitude *z* (m) uses the
  [standard atmosphere](https://www.engineeringtoolbox.com/air-altitude-pressure-d_462.html):
  $$p = 101325\,(1 - 2.25577\times10^{-5}\,z)^{5.25588}\ \text{Pa}$$
- The dew point is held constant through the day, so the amount of water in the air stays the same
  while the relative humidity changes with temperature.

### Thermal (long-wave) radiation

Every surface radiates heat according to the
[Stefan–Boltzmann law](https://en.wikipedia.org/wiki/Stefan%E2%80%93Boltzmann_law):

$$q = \varepsilon\,\sigma\,(T_1^4 - T_2^4) \qquad \sigma = 5.670\times10^{-8}\ \text{W/m}^2\text{K}^4$$

The roof and the canopy above it are treated as **two large parallel grey plates**. Their exchange
factor is a standard textbook result (e.g. Incropera, *Fundamentals of Heat and Mass Transfer*,
ch. 13):

$$F = \frac{1}{1/\varepsilon_1 + 1/\varepsilon_2 - 1}$$

`gap_view` (0.85) is the share of the roof's view that the canopy takes up. The rest looks out
through the open sides.

### Wind convection

```
h = 2.8 + 3.0·v   W/m²K   (v = wind speed in m/s)
```

This is the **Watmuff, Charters & Proctor (1977)** correlation for flat plates in wind. It is often
quoted via Duffie & Beckman, *Solar Engineering of Thermal Processes*. It is McAdams' older formula
(5.7 + 3.8·v) with the radiation part taken out. That is correct here, because radiation is modelled
separately and must not be counted twice.

The air speed in the gap under the canopy is `wind_share` (0.5) × the open wind. When the stage-2 fan
runs, it is raised to at least `fan_speed`.

Compared with roof-specific measurements such as Sharples & Charlesworth (1998, about 6.5 + 3.3·v),
Watmuff gives lower values, so it is a conservative choice. *v* should be the wind speed at roof
level. Weather stations measure at 10 m height, where it is usually stronger.

### Evaporation from the wet fabric: the Lewis relation

This is the key formula for CoolHead. Heat and water vapour travel through the thin layer of air at
a surface in almost the same way. So once we know the heat transfer coefficient *h* (from the wind
formula above), we also know the **mass transfer coefficient** *g* for water vapour:

$$g = \frac{h}{c_p\,Le^{2/3}} \approx \frac{h}{c_p} \quad \text{(kg/m}^2\text{s)}$$

This is the **[Lewis relation](https://en.wikipedia.org/wiki/Lewis_number)**. The model takes the
Lewis number *Le* of air and water vapour as 1. Its real value is about 0.85, so the model slightly
*underestimates* evaporation, by about 10%. The evaporation rate is then:

$$E = g\,\big(W_s(T_{fabric}) - W_{air}\big) \quad \text{kg/m}^2\text{s}$$

$W_s(T_{fabric})$ is the humidity ratio of saturated air at the fabric's own temperature. The
difference is how much "drier" the passing air is than the wet surface. *E* is never allowed to be
negative (no dew forming on the fabric).

Each kg of water evaporated takes $L_V = 2.43$ MJ of heat away from the fabric. That is the
[latent heat](https://en.wikipedia.org/wiki/Latent_heat) of water at about 30 °C. $c_p = 1006$ J/kgK
is the heat capacity of dry air.

The model applies this on **both sides** of the fabric: the top side with the open-wind *h*, the
underside with the gap *h*.

**There is no cloth-specific coefficient.** The formula treats the fabric as a perfectly wet water
surface, which is the upper limit. That is why v2 adds `wet_fraction` (see below).

### Fabric temperature

The canopy is thin enough to have no heat storage. At each time step its temperature is the value
at which its energy balance is zero:

```
sun absorbed + radiation (sky, roof, surroundings) + convection (both sides) − evaporation × L_V = 0
```

It is solved by **bisection**. The balance always falls as the fabric gets hotter, so there is exactly
one answer. Dry and wet fabric have different solar absorptance, solar transmittance and emissivity.

### Roof slab

Heat flows down through the concrete according to the 1-D
[heat equation](https://en.wikipedia.org/wiki/Heat_equation):

$$\frac{\partial T}{\partial t} = \alpha\,\frac{\partial^2 T}{\partial x^2} \qquad \alpha = \frac{k}{\rho\,c}$$

It is solved with **explicit finite differences**
([FTCS scheme](https://en.wikipedia.org/wiki/FTCS_scheme)) on 15 layers. The two surface layers hold
half a layer's worth of concrete each. The scheme is stable only when the **Fourier number**
$\alpha\,\Delta t / \Delta x^2 \le 0.5$. The model refuses settings above 0.4 to leave headroom at the
surfaces; the defaults give 0.2.

Heat into the room through the ceiling:

$$q_{in} = h_{in}\,(T_{ceiling} - T_{room}) \qquad h_{in} = 6.1\ \text{W/m}^2\text{K}$$

$h_{in}$ is the ASHRAE combined (convection + radiation) surface coefficient for a horizontal surface
with heat flowing down. Daily heat in counts only heat flowing *into* the room.

## Version 2 changes and why

v1 is the original notebook model, with its physics unchanged. v2 adds the fixes from
`initial_findings.md`. `cm.DEFAULT_MODEL_VERSION` is `"v2"`.

### 1. Wet fabric lets more sunlight through (transmittance 0.08 → 0.20)

**Why:** v1 made wet fabric *less* see-through than dry fabric (0.08 vs 0.10), which is backwards.
Water fills the gaps between cotton fibres, so they scatter less light and more gets through. This
is the well-known reason a wet T-shirt protects less against sunburn. Osterwalder et al. (2000)
measured bleached cotton letting through about 30% of UV dry and about 50% wet. Gambichler et al.
(2002) found cotton's UV protection factor dropped significantly when wet.

0.20 is an estimate in the 0.15–0.25 range. These studies measured UV, not the full solar spectrum,
and it depends on the weave. **This one number changes the result the most**, so measuring it
with the light-through-cloth experiment in `experiment_transp.md` would be very valuable.

### 2. Wetness factor `wet_fraction` (new, default 1.0)

**Why:** v1 treats the cloth as a perfectly wet water surface on both sides, which gives the maximum
possible evaporation. Real cotton has drier patches, the water supply may not keep up, and the
underside may be less wet than the top. `wet_fraction` multiplies the evaporation rate.

It stays at 1.0 until it is measured with the cloth-weighing experiment in `experiment_evap.md`
(*f_wet = measured ÷ predicted*).

### 3. The roof's open sides see the surroundings, not the sky

**Why:** looking out sideways from under a canopy you see walls, trees and the horizon. Those are at
about air temperature, not the cold sky. v1 was also inconsistent: the *fabric's* underside already
used air temperature for that same view, while the roof used the sky. In v1, the roof was losing
heat to a cold sky it couldn't really see.

### 4. The air in the gap is modelled as its own node

v1 assumed the air under the canopy is plain outdoor air. v2 treats the gap as a well-mixed box that
outdoor air flows through:

- Air flow per m² of roof: $\dot m = \rho\,v_{gap}\,H / L$, with $\rho = p / (R\,T)$,
  *H* = `gap_height`, *L* = `flow_length`.
- **Heat balance:** the air coming in at $T_a$ is warmed or cooled by the fabric underside and the
  roof:
  $$\dot m\,c_p\,(T_{gap} - T_a) = h_{gap}(T_{fabric} - T_{gap}) + h_{gap}(T_{roof} - T_{gap})$$
- **Vapour balance:** the water picked up from the fabric underside raises the gap air's humidity:
  $$\dot m\,(W_{gap} - W_{air}) = g_{gap}\,\big(W_s(T_{fabric}) - W_{gap}\big)$$

Both are solved together with the fabric's energy balance at every time step.

**Why:** the outdoor-air assumption is wrong in two opposite ways. It makes underside evaporation too
high, because in reality the gap air gets more humid. It also makes the gap air too warm, because in
reality the wet cloth and cool roof cool it. v1's conclusions that "more wind lets more heat in" and
"the fan never helps" depend directly on this assumption.

### Effect of each change

June, wet canopy (08–19 h), heat into the room compared with a bare roof:

| Model | Heat in (Wh/m²/day) | Cut vs bare |
|---|---|---|
| v1 (notebook) | 300 | 74% |
| v1 + fix 1 (wet transmittance) | 452 | 61% |
| v1 + fix 3 (open sides) | 398 | 66% |
| v1 + fix 4 (gap air) | 277 | 76% |
| **v2 (all fixes)** | **533** | **54%** |

Fix 2 has no effect at its default of 1.0. In v2 the wet canopy performs about the same as white
paint (55%) on a June day. The dry canopy drops from 53% to 45%.

## All settings

| Setting | Meaning | Unit | v1 | v2 |
|---|---|---|---|---|
| `room_c` | Indoor air temperature (AC set point) | °C | 26.0 | 26.0 |
| `h_in` | Ceiling-to-room heat transfer (ASHRAE, heat flowing down) | W/m²K | 6.1 | 6.1 |
| `slab_thick` | Slab thickness | m | 0.15 | 0.15 |
| `slab_k` | Slab conductivity | W/mK | 1.6 | 1.6 |
| `slab_rho` | Slab density | kg/m³ | 2400 | 2400 |
| `slab_c` | Slab specific heat | J/kgK | 880 | 880 |
| `slab_nodes` | Slab layers in the calculation | | 15 | 15 |
| `bare_absorptance` | Bare concrete: solar absorptance | | 0.70 | 0.70 |
| `bare_emissivity` | Bare concrete: emissivity | | 0.90 | 0.90 |
| `white_absorptance` | White paint: solar absorptance | | 0.30 | 0.30 |
| `white_emissivity` | White paint: emissivity | | 0.90 | 0.90 |
| `sheet_absorptance` | Sheet under canopy: solar absorptance | | 0.65 | 0.65 |
| `sheet_emissivity` | Sheet under canopy: emissivity | | 0.90 | 0.90 |
| `dry_fabric_absorptance` | Dry fabric: solar absorptance | | 0.35 | 0.35 |
| `dry_fabric_transmittance` | Dry fabric: solar transmittance | | 0.10 | 0.10 |
| `dry_fabric_emissivity` | Dry fabric: emissivity | | 0.88 | 0.88 |
| `wet_fabric_absorptance` | Wet fabric: solar absorptance | | 0.45 | 0.45 |
| `wet_fabric_transmittance` | Wet fabric: solar transmittance | | 0.08 | **0.20** |
| `wet_fabric_emissivity` | Wet fabric: emissivity | | 0.95 | 0.95 |
| `gap_view` | Share of the roof's view taken up by the canopy | | 0.85 | 0.85 |
| `wind_share` | Wind speed in the gap as a share of the open wind | | 0.5 | 0.5 |
| `fan_speed` | Air speed in the gap when the stage-2 fan runs | m/s | 1.5 | 1.5 |
| `wet_start`, `wet_end` | Fabric kept wet from / until | h | 8 – 19 | 8 – 19 |
| `peak_start`, `peak_end` | Water-saving schedule: wet from / until | h | 11 – 17 | 11 – 17 |
| `wet_fraction` | Wetness factor (1 = perfectly wet) | | — | 1.0 |
| `gap_height` | Height of the gap under the canopy | m | — | 0.5 |
| `flow_length` | Distance air travels under the canopy | m | — | 6.0 |
| `dt` | Time step | s | 30 | 30 |
| `spinup_days` | Days repeated until the slab settles | | 5 | 5 |

The weather inputs are part of each `Scenario`, not the settings. They are date, `tmax`, `tmin`,
`dewpoint`, `wind` (default 2 m/s), `sun_factor` (default 1.0) and site (default Faisalabad, 31.42 °N,
73.08 °E, 184 m).

## Known limitations

- **Clear sky only**, apart from the simple `sun_factor` scaling. There are no real cloud or weather
  records.
- **One dimension:** the roof is treated as infinitely wide. Edges, parapets and the canopy frame are
  ignored.
- **The fabric is wet or dry instantly**, according to the schedule. Real cloth dries out gradually
  after the pump stops.
- **The fan rule** (`tr > ta + 0.5`, calm wind, wet fabric) never triggers, because a wet-shaded roof
  is always cooler than the air. It needs rethinking, now that v2 models the gap air.
- **The fabric's thermal radiation is assumed opaque**, and porous cloth lets some through.
- **Only the cloth itself can be checked by the planned experiments**: evaporation
  (`experiment_evap.md`) and sunlight transmittance (`experiment_transp.md`). The slab and gap
  parts are not yet tested against measurements.

## References

- **Alduchov, O. A. & Eskridge, R. E. (1996).** Improved Magnus form approximation of saturation
  vapor pressure. *Journal of Applied Meteorology* 35, 601–609.
  [doi:10.1175/1520-0450(1996)035<0601:IMFAOS>2.0.CO;2](https://doi.org/10.1175/1520-0450(1996)035%3C0601:IMFAOS%3E2.0.CO;2)
- **ASHRAE (2009 and later).** *ASHRAE Handbook – Fundamentals*: ch. 14 (Climatic design
  information: daily temperature range profile) and ch. 26 (Surface heat transfer coefficients).
- **Berdahl, P. & Martin, M. (1984).** Emissivity of clear skies. *Solar Energy* 32(5), 663–664.
  [doi:10.1016/0038-092X(84)90144-0](https://doi.org/10.1016/0038-092X(84)90144-0)
- **Duffie, J. A. & Beckman, W. A.** *Solar Engineering of Thermal Processes* (Wiley). Wind heat
  transfer coefficients, including Watmuff et al. and McAdams.
- **Gambichler, T. et al. (2002).** Influence of wetness on the ultraviolet protection factor (UPF)
  of textiles: in vitro and in vivo measurements.
  [PubMed 11982919](https://pubmed.ncbi.nlm.nih.gov/11982919/)
- **Incropera, F. P. et al.** *Fundamentals of Heat and Mass Transfer* (Wiley). Heat and mass
  transfer analogy, radiation between parallel plates, finite-difference stability.
- **Ineichen, P. & Perez, R. (2002).** A new airmass independent formulation for the Linke turbidity
  coefficient. *Solar Energy* 73(3), 151–157.
  [doi:10.1016/S0038-092X(02)00045-2](https://doi.org/10.1016/S0038-092X(02)00045-2).
  Implemented in [pvlib `clearsky.ineichen`](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.ineichen.html).
- **Lewis, W. K. (1922).** The evaporation of a liquid into a gas. *Transactions of the ASME* 44,
  325–340. Background: [Lewis number](https://en.wikipedia.org/wiki/Lewis_number).
- **Osterwalder, U. et al. (2000)**, cited in Wong, W. Y. et al. (2014). Effect of stretching on
  ultraviolet protection of cotton and cotton/Coolmax blended weft knitted fabric in a wet state.
  *Materials* 7(1), 58. [PMC5453141](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5453141/)
- **Sharples, S. & Charlesworth, P. S. (1998).** Full-scale measurements of wind-induced convective
  heat transfer from a roof-mounted flat plate solar collector. *Solar Energy* 62(2), 69–77.
- **Watmuff, J. H., Charters, W. W. S. & Proctor, D. (1977).** Solar and wind induced external
  coefficients for solar collectors. *COMPLES* 2, 56.
- Climate averages for Faisalabad (June and July maximum and minimum temperatures and humidity):
  [Wikipedia, Faisalabad – Climate](https://en.wikipedia.org/wiki/Faisalabad#Climate)
