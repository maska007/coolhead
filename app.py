"""CoolHead roof model explorer.  Run with:  env/bin/streamlit run app.py"""
import dataclasses

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import coolhead_model as cm

st.set_page_config(page_title="CoolHead roof model", page_icon="🏠", layout="wide")

# ---------------- colours (validated categorical palette; same hues as the slide charts) ----------------
LIGHT = dict(bare="#eb6834", white="#eda100", dry_canopy="#1baf7a", wet_canopy="#2a78d6",
             wet_canopy_peak="#e87ba4", wet_canopy_fan="#6250d6", air="#898781",
             ink="#0b0b0b", ink2="#52514e", grid="#e1e0d9", neutral="#f0efec")
DARK = dict(bare="#d95926", white="#c98500", dry_canopy="#199e70", wet_canopy="#3987e5",
            wet_canopy_peak="#d55181", wet_canopy_fan="#9085e9", air="#898781",
            ink="#f0efec", ink2="#c3c2b7", grid="#2c2c2a", neutral="#383835")
theme = getattr(getattr(st.context, "theme", None), "type", None)
COL = DARK if theme == "dark" else LIGHT
NAME = {"bare": "Bare concrete", "white": "White paint", "dry_canopy": "Dry canopy",
        "wet_canopy": "CoolHead wet 08–19 h", "wet_canopy_peak": "CoolHead wet 11–17 h",
        "wet_canopy_fan": "CoolHead wet + fan"}

INT_SETTINGS = {"slab_nodes", "spinup_days"}


@st.cache_data(show_spinner=False, max_entries=256)
def simulate(version, settings: dict, scenario: dict, case):
    model = cm.create_model(version, settings=cm.Settings(**settings))
    sc = cm.Scenario(**{**scenario, "site": cm.FAISALABAD})
    return model.run(case, sc)


def base_layout(fig, height=440, **kw):
    layout = dict(height=height, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                  legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), font=dict(color=COL["ink2"]))
    fig.update_layout(**{**layout, **kw})
    fig.update_xaxes(gridcolor=COL["grid"], zeroline=False)
    fig.update_yaxes(gridcolor=COL["grid"], zeroline=False)
    return fig


# ---------------- sidebar: model, weather, cases, hidden settings ----------------
with st.sidebar:
    st.header("Model")
    versions = list(cm.MODELS)
    version = st.radio("Model version", versions, index=versions.index(cm.DEFAULT_MODEL_VERSION),
                       horizontal=True, key="version", format_func=lambda v: f"{v} – {cm.MODELS[v].description}",
                       help="v1 is the original notebook model. v2 adds the fixes from the model "
                            "review (see model_readme.md).")

    st.header("Weather")
    preset_name = st.selectbox("Start from", list(cm.SCENARIOS))
    preset = cm.SCENARIOS[preset_name]
    k = preset_name                                   # slider keys follow the preset, so switching resets them
    date = st.date_input("Date (sets the sun's path)", pd.Timestamp(preset.date).date(), key=f"{k}date")
    tmin, tmax = st.slider("Air temperature, min – max (°C)", 0.0, 50.0, (preset.tmin, preset.tmax), 0.5,
                           key=f"{k}temp")
    dewpoint = st.slider("Dew point (°C) – higher = more humid", -5.0, 30.0, preset.dewpoint, 0.5,
                         key=f"{k}dew")
    wind = st.slider("Wind at roof level (m/s)", 0.1, 6.0, preset.wind, 0.1, key=f"{k}wind")
    sun = st.slider("Sun strength (1 = cloudless sky)", 0.1, 1.0, preset.sun_factor, 0.05, key=f"{k}sun")

    st.header("Cases")
    cases = st.multiselect("Show", list(cm.CASES), default=[c for c in cm.CASES if c != "wet_canopy_fan"],
                           format_func=NAME.get)

    defaults = cm.default_settings(version)
    with st.expander("Model settings", expanded=False):
        st.caption("Every assumption in the model. Changes apply to the selected version only.")
        if st.button("Reset to defaults"):
            for key in [key for key in st.session_state if key.startswith(f"set_{version}_")]:
                del st.session_state[key]
        values = {}
        for row in cm.settings_info(version):
            name, default = row["name"], row["default"]
            label = row["label"] + (f" ({row['unit']})" if row["unit"] else "")
            if name in INT_SETTINGS:
                values[name] = st.number_input(label, value=int(default), step=1, key=f"set_{version}_{name}")
            else:
                values[name] = st.number_input(label, value=float(default), format="%g",
                                               step=0.05 if abs(default) <= 1 else 1.0,
                                               key=f"set_{version}_{name}")
        changed = [n for n, v in values.items() if v != getattr(defaults, n)]
        if changed:
            st.caption("Changed: " + ", ".join(changed))

settings = {**dataclasses.asdict(defaults), **values}
scenario = dict(date=str(date), tmax=tmax, tmin=tmin, dewpoint=dewpoint, wind=wind, sun_factor=sun)

# ---------------- run ----------------
st.title("CoolHead roof model")
st.caption(f"Model **{version}** · computer model, not measurements · flat 150 mm concrete roof, "
           f"Faisalabad, clear-sky design day on {date:%d %b}")

if tmax <= tmin:
    st.error("The maximum air temperature must be higher than the minimum.")
    st.stop()
try:
    cm.create_model(version, settings=cm.Settings(**settings))     # validates settings
except ValueError as e:
    st.error(f"These settings don't work: {e}")
    st.stop()

if not cases:
    st.info("Pick at least one case in the sidebar.")
    st.stop()
needed = list(dict.fromkeys(["bare", "wet_canopy"] + cases))
with st.spinner("Running the model…"):
    runs = {c: simulate(version, settings, scenario, c) for c in needed}
hourly = {c: runs[c][0] for c in needed}
summary = pd.DataFrame([runs[c][1] for c in needed]).set_index("case")
summary["heat_cut_vs_bare_pct"] = 100 * (1 - summary.heat_in_Wh_m2_day / summary.loc["bare", "heat_in_Wh_m2_day"])

# ---------------- headline numbers ----------------
bare, wet = summary.loc["bare"], summary.loc["wet_canopy"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Peak roof, bare", f"{bare.peak_roof_C:.1f} °C")
m2.metric("Peak roof, CoolHead wet", f"{wet.peak_roof_C:.1f} °C",
          f"{wet.peak_roof_C - bare.peak_roof_C:+.1f} °C vs bare", delta_color="inverse")
m3.metric("Heat into room per day, CoolHead wet", f"{wet.heat_in_Wh_m2_day:,.0f} Wh/m²",
          f"{-wet.heat_cut_vs_bare_pct:.0f}% vs bare", delta_color="inverse")
m4.metric("Water used per day, CoolHead wet", f"{wet.water_L_m2_day:.1f} L/m²")

tab_day, tab_heat, tab_cut, tab_table = st.tabs(["Through the day", "Heat into the room", "Roof cross-section", "Data"])

# ---------------- 1. temperatures through the day ----------------
with tab_day:
    VARS = {"Roof surface (°C)": "roof_C", "Ceiling (°C)": "ceiling_C", "Fabric (°C)": "fabric_C",
            "Gap air under canopy (°C)": "gap_C", "Heat into room (W/m²)": "heat_in_Wm2",
            "Water evaporating (L/m² per hour)": "evap_kg_m2s"}
    var_label = st.radio("Show", list(VARS), horizontal=True, label_visibility="collapsed")
    var = VARS[var_label]
    fig = go.Figure()
    if var.endswith("_C") and var != "ceiling_C":
        air = hourly["bare"]
        fig.add_scatter(x=air.hour, y=air.air_C, name="Outdoor air", line=dict(color=COL["air"], width=2, dash="dash"),
                        hovertemplate="%{y:.1f}")
    shown = 0
    for c in cases:
        d = hourly[c]
        y = d[var] * 3600 if var == "evap_kg_m2s" else d[var]
        if y.isna().all() or (var == "evap_kg_m2s" and not (y > 0).any()):
            continue
        shown += 1
        fig.add_scatter(x=d.hour, y=y, name=NAME[c], line=dict(color=COL[c], width=2),
                        hovertemplate="%{y:.2f}" if var == "evap_kg_m2s" else "%{y:.1f}")
    if var == "roof_C":
        s = cm.Settings(**settings)
        fig.add_vrect(x0=s.wet_start, x1=s.wet_end, fillcolor=COL["wet_canopy"], opacity=0.06, line_width=0,
                      annotation_text="fabric kept wet", annotation_position="bottom left")
    base_layout(fig, yaxis_title=var_label,
                xaxis=dict(title="Time of day", tickvals=list(range(0, 25, 3)),
                           ticktext=[f"{h:02d}:00" for h in range(0, 25, 3)], range=[0, 24]))
    if shown == 0:
        st.info("None of the selected cases has this value (for example, only canopy cases have a fabric).")
    st.plotly_chart(fig, width="stretch")

# ---------------- 2. heat into the room + water ----------------
with tab_heat:
    left, right = st.columns([3, 2])
    order = [c for c in cases][::-1]
    t = summary.loc[order]
    fig = go.Figure(go.Bar(
        y=[NAME[c] for c in order], x=t.heat_in_Wh_m2_day, orientation="h",
        marker=dict(color=[COL[c] for c in order], line=dict(color="rgba(0,0,0,0)", width=2)),
        text=[f"{v:,.0f}" + ("" if c == "bare" else f"  (−{p:.0f}%)")
              for c, v, p in zip(order, t.heat_in_Wh_m2_day, t.heat_cut_vs_bare_pct)],
        textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x:,.0f} Wh/m²<extra></extra>"))
    base_layout(fig, height=60 * len(order) + 120, hovermode="closest", showlegend=False, bargap=0.35,
                xaxis_title="Heat into the room over 24 h (Wh per m² of roof)  ·  % = cut vs bare concrete")
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(range=[0, summary.heat_in_Wh_m2_day.max() * 1.3])
    left.plotly_chart(fig, width="stretch")

    wet_cases = [c for c in cases if "wet" in c]
    if wet_cases:
        w = summary.loc[wet_cases[::-1]]
        fig = go.Figure(go.Bar(y=[NAME[c] for c in w.index], x=w.water_L_m2_day, orientation="h",
                               marker_color=[COL[c] for c in w.index], text=[f"{v:.1f} L" for v in w.water_L_m2_day],
                               textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: %{x:.1f} L/m²<extra></extra>"))
        base_layout(fig, height=60 * len(w) + 120, hovermode="closest", showlegend=False, bargap=0.35,
                    xaxis_title="Water evaporated per day (L/m²)")
        fig.update_yaxes(showgrid=False)
        fig.update_xaxes(range=[0, w.water_L_m2_day.max() * 1.35])
        right.plotly_chart(fig, width="stretch")
        if summary.loc[wet_cases].fan_hours.sum() == 0 and "wet_canopy_fan" in cases:
            right.caption("The stage-2 fan never switched on: its rule (calm, fabric wet, roof hotter than air) "
                          "was not met.")

# ---------------- 3. animated cross-section ----------------
with tab_cut:
    canopy_cases = sorted([c for c in cases if "canopy" in c] or ["wet_canopy"], key=lambda c: c != "wet_canopy")
    case = st.selectbox("Case", canopy_cases + [c for c in cases if c not in canopy_cases], format_func=NAME.get)
    d = hourly.get(case, hourly["bare"]).iloc[::60].reset_index(drop=True)      # every 30 minutes
    room = settings["room_c"]
    layers = (["Outdoor air", "Fabric", "Gap air", "Roof surface", "Ceiling", "Room"] if "canopy" in case
              else ["Outdoor air", "Roof surface", "Ceiling", "Room"])
    cols = {"Outdoor air": "air_C", "Fabric": "fabric_C", "Gap air": "gap_C", "Roof surface": "roof_C",
            "Ceiling": "ceiling_C"}

    def column(row):
        return [[row[cols[l]] if l in cols else room] for l in layers]

    def title(row):
        return f"{int(row.hour):02d}:{int(round(row.hour % 1 * 60)):02d}  ·  sun {row.sun_Wm2:,.0f} W/m²"

    span = max(5.0, float(np.nanmax(np.abs(d[[cols[l] for l in layers if l in cols]].to_numpy() - room))))
    scale = [[0, "#184f95"], [0.5, COL["neutral"]], [1, "#e34948"]]

    def heat(row):
        z = column(row)
        return go.Heatmap(z=z, y=layers, x=[""], zmin=room - span, zmax=room + span, colorscale=scale,
                          text=[[f"{v[0]:.1f} °C"] for v in z], texttemplate="%{text}", textfont=dict(size=16),
                          colorbar=dict(title="°C"), hovertemplate="%{y}: %{text}<extra></extra>", xgap=0, ygap=3)

    start = int(d.hour.sub(14).abs().idxmin())
    fig = go.Figure(heat(d.iloc[start]),
                    frames=[go.Frame(data=[heat(r)], name=str(i), layout=dict(title_text=title(r)))
                            for i, r in d.iterrows()])
    fig.update_layout(
        height=470, title_text=title(d.iloc[start]), margin=dict(l=10, r=10, t=50, b=10),
        font=dict(color=COL["ink2"]), yaxis=dict(autorange="reversed"), xaxis=dict(visible=False),
        updatemenus=[dict(type="buttons", direction="left", x=0, y=-0.08, xanchor="left", yanchor="top",
                          buttons=[dict(label="▶ Play", method="animate",
                                        args=[None, dict(frame=dict(duration=250, redraw=True), fromcurrent=True)]),
                                   dict(label="⏸ Pause", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
        sliders=[dict(active=start, x=0.18, y=-0.08, len=0.82, currentvalue=dict(visible=False),
                      steps=[dict(label=f"{int(r.hour):02d}:{int(round(r.hour % 1 * 60)):02d}"
                                  if i % 6 == 0 else "", method="animate",
                                  args=[[str(i)], dict(mode="immediate", frame=dict(duration=0, redraw=True))])
                             for i, r in d.iterrows()])])
    st.plotly_chart(fig, width="stretch")
    st.caption(f"A cut down through the roof. Red layers are warmer than the {room:g} °C room, blue ones cooler. "
               "Press Play to run through the day.")

# ---------------- 4. data table ----------------
with tab_table:
    cols_out = ["peak_roof_C", "mean_roof_C", "peak_fabric_C", "peak_ceiling_C", "heat_in_Wh_m2_day",
                "heat_cut_vs_bare_pct", "peak_heat_in_Wm2", "water_L_m2_day", "fan_hours"]
    headers = {"peak_roof_C": "Peak roof °C", "mean_roof_C": "Mean roof °C", "peak_fabric_C": "Peak fabric °C",
               "peak_ceiling_C": "Peak ceiling °C", "heat_in_Wh_m2_day": "Heat in, Wh/m² per day",
               "heat_cut_vs_bare_pct": "Cut vs bare %", "peak_heat_in_Wm2": "Peak heat in, W/m²",
               "water_L_m2_day": "Water, L/m² per day", "fan_hours": "Fan hours"}
    table = summary.loc[cases, cols_out].astype(float).rename(index=NAME, columns=headers).round(1)
    table.index.name = "Case"
    st.dataframe(table.map(lambda v: "–" if pd.isna(v) else f"{v:,.1f}"), width="stretch")
    st.download_button("Download this table (CSV)", table.to_csv().encode(), "coolhead_summary.csv", "text/csv")
