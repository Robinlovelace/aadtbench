#!/usr/bin/env python3
"""Update the headline leaderboard table in README.md and regenerate assets/hero-benchmark.png."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "leaderboard-summary.csv"
DEFAULT_README = ROOT / "README.md"
DEFAULT_FIG = ROOT / "assets" / "hero-benchmark.png"

START_MARKER = "<!-- LEADERBOARD:START -->"
END_MARKER = "<!-- LEADERBOARD:END -->"

MODES = [
    ("car", "Car"),
    ("heavy", "Heavy"),
    ("cycling", "Cycling"),
    ("walking", "Walking"),
]

TOOL_META = [
    ("sdna", "sDNA", "T0", "D", "#8c564b"),
    ("cityseer_od", "cityseer", "T2", "s", "#eb6834"),
    ("aequilibrae", "AequilibraE", "T2", "^", "#1baf7a"),
    ("una", "UNA", "T1", "P", "#9467bd"),
    ("baseline", "Best baseline", "T1", "o", "#2a78d6"),
]

CPU_W_PER_THREAD = {
    "AMD Ryzen Threadripper PRO 9975WX 32-Cores": 350.0 / 64.0,
}


def load_board(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[
        (df["status"] == "complete")
        & (df["split"] == "group_out_pooled")
        & (df["track"] == "uncalibrated")
        & (df["n_sites"] >= 20)
        & df["rho"].notna()
    ].copy()
    w_per_thr = df["cpu_model"].map(CPU_W_PER_THREAD).fillna(6.0)
    df["energy_wh"] = df["cpu_time_s"] * w_per_thr / 3600.0
    return df


def best_variant_per_tool_mode(df: pd.DataFrame) -> dict[tuple[str, str], dict]:
    """Return the highest median-rho fixed variant for each (tool, mode)."""
    out: dict[tuple[str, str], dict] = {}
    for tool_id, _, _, _, _ in TOOL_META:
        for mode_id, _ in MODES:
            sub = df[(df["tool"] == tool_id) & (df["mode"] == mode_id)]
            if sub.empty:
                continue
            grp = (
                sub.groupby("variant")
                .agg(
                    n=("case_id", "nunique"),
                    med_rho=("rho", "median"),
                    mean_rho=("rho", "mean"),
                    med_r2=("log_r2", "median"),
                    med_wall=("wall_time_s", "median"),
                    med_wh=("energy_wh", "median"),
                )
                .sort_values(["med_rho", "mean_rho"], ascending=False)
            )
            top_var = grp.index[0]
            row = grp.iloc[0].to_dict()
            row["variant"] = top_var
            out[(tool_id, mode_id)] = row
    return out


def tool_resource_summary(df: pd.DataFrame, tool_id: str) -> tuple[float, float]:
    """Median wall time (s) and energy (Wh/city) across the tool's non-baseline variants."""
    sub = df[df["tool"] == tool_id].drop_duplicates(["case_id", "tool", "variant", "input_tier"])
    if sub.empty:
        return (np.nan, np.nan)
    return (float(sub["wall_time_s"].median()), float(sub["energy_wh"].median()))


def format_wall(sec: float) -> str:
    if pd.isna(sec):
        return "—"
    if sec < 1.0:
        return f"{sec:.1f} s"
    if sec < 120:
        return f"{sec:.0f} s"
    return f"{sec / 60:.1f} min"


def format_wh(wh: float) -> str:
    if pd.isna(wh):
        return "—"
    if wh < 0.01:
        return "<0.01"
    if wh < 1.0:
        return f"{wh:.2f}"
    return f"{wh:.1f}"


def build_markdown_table(df: pd.DataFrame) -> str:
    best = best_variant_per_tool_mode(df)
    mode_counts = {
        m: int(df[df["mode"] == m]["case_id"].nunique()) for m, _ in MODES
    }
    open_tools = [t[0] for t in TOOL_META if t[0] != "baseline"]
    mode_leaders = {}
    for m, _ in MODES:
        scores = [(best[(t, m)]["med_rho"], t) for t in open_tools if (t, m) in best]
        mode_leaders[m] = max(scores)[1] if scores else None

    headers = [
        "Tool",
        "Tier",
        *[f"{label} ({mode_counts[m]})" for m, label in MODES],
        "Median wall*",
        "Wh/city*",
    ]
    align = ["---", ":---:", *(":---:" for _ in MODES), "---:", "---:"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(align) + " |",
    ]

    for tool_id, label, tier, _, _ in TOOL_META:
        cells = [f"**{label}**" if tool_id != "baseline" else label, f"`{tier}`"]
        for m, _ in MODES:
            info = best.get((tool_id, m))
            if not info:
                cells.append("—")
                continue
            val = f"{info['med_rho']:.3f}"
            if tool_id == mode_leaders[m]:
                val = f"**{val}**"
            cells.append(val)
        # Report wall time and Wh/city range or median across variants
        sub_t = df[df["tool"] == tool_id].drop_duplicates(["case_id", "tool", "variant", "input_tier"])
        v_meds = sub_t.groupby("variant")[["wall_time_s", "energy_wh"]].median()
        if tool_id == "baseline":
            wall_str = "<1 s"
            wh_str = "<0.01"
        elif len(v_meds) > 1 and v_meds["wall_time_s"].max() / max(v_meds["wall_time_s"].min(), 0.1) > 3:
            wall_str = f"{format_wall(v_meds['wall_time_s'].min())}–{format_wall(v_meds['wall_time_s'].max())}"
            wh_str = f"{format_wh(v_meds['energy_wh'].min())}–{format_wh(v_meds['energy_wh'].max())}"
        else:
            wall_str = format_wall(v_meds["wall_time_s"].median())
            wh_str = format_wh(v_meds["energy_wh"].median())
        cells.extend([wall_str, wh_str])
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(
        "_Median spatial group-out Spearman ρ across all cities with ≥ 20 sites "
        "(best fixed variant per tool; **bold** = top open tool per mode). "
        "Top variants: Car/Heavy = `sDNA mode_hybrid` (log R² = +0.50 / +0.45); "
        "Cycling = `cityseer dispersed` (0.552; `UNA default` wins 4/8 cities); "
        "Walking = `baseline attractor_density` (0.589), `sDNA bt_eucl` (0.507), "
        "`cityseer dispersed` (mean 0.520), `AequilibraE UE` (mean 0.510). "
        "*Per-city wall time and TDP-proportional CPU energy across variants (fastest to heaviest)._"
    )
    return "\n".join(lines)


def build_hero_figure(df: pd.DataFrame, out_path: Path) -> None:
    best = best_variant_per_tool_mode(df)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 3.8), gridspec_kw={"width_ratios": [1.15, 1.0]})
    fig.patch.set_facecolor("white")

    # Panel (a): Median Spearman rho by mode (best fixed variant per tool)
    y_base = np.arange(len(MODES))[::-1]
    offsets = np.linspace(0.24, -0.24, len(TOOL_META))
    for (tool_id, label, _, marker, color), dy in zip(TOOL_META, offsets):
        xs = [best.get((tool_id, m), {}).get("med_rho", np.nan) for m, _ in MODES]
        ys = y_base + dy
        ax1.hlines(ys, 0, xs, color=color, alpha=0.22, lw=1.4, zorder=1)
        ax1.scatter(xs, ys, s=48, marker=marker, color=color, edgecolor="white", lw=0.7, label=label, zorder=3)

    # Annotate top open tool per mode
    open_tools = [t[0] for t in TOOL_META if t[0] != "baseline"]
    for idx, (m, _) in enumerate(MODES):
        top_t = max(open_tools, key=lambda t: best.get((t, m), {}).get("med_rho", -1))
        top_v = best[(top_t, m)]["med_rho"]
        t_idx = [t[0] for t in TOOL_META].index(top_t)
        ax1.text(
            top_v + 0.018,
            y_base[idx] + offsets[t_idx],
            f"{top_v:.2f}",
            va="center",
            ha="left",
            fontsize=7.5,
            fontweight="bold",
            color=TOOL_META[t_idx][4],
        )
        # Also label baseline when it beats all open tools (walking)
        bl_v = best.get(("baseline", m), {}).get("med_rho", -1)
        if bl_v > top_v:
            b_idx = [t[0] for t in TOOL_META].index("baseline")
            ax1.text(
                bl_v + 0.018,
                y_base[idx] + offsets[b_idx],
                f"{bl_v:.2f}",
                va="center",
                ha="left",
                fontsize=7.5,
                fontweight="bold",
                color=TOOL_META[b_idx][4],
            )

    ax1.set_yticks(y_base)
    ax1.set_yticklabels([f"{lbl}\n({df[df['mode']==m]['case_id'].nunique()} cities)" for m, lbl in MODES], fontsize=8.5)
    ax1.set_xlim(0.35, 0.90)
    ax1.set_xlabel("Median Spearman $\\rho$ (spatial group-out)", fontsize=8.5, color="#333333")
    ax1.set_title("(a) Best fixed variant by mode", fontsize=9.5, loc="left", fontweight="bold", color="#222222")
    ax1.grid(axis="x", color="#eaeae6", lw=0.7, zorder=0)
    ax1.legend(fontsize=7.5, frameon=False, loc="lower right", ncol=1)

    # Panel (b): Car accuracy vs median wall time (log scale), annotated with Wh/city
    car = df[(df["mode"] == "car") & (df["tool"] != "baseline")]
    vstats = (
        car.groupby(["tool", "variant"])
        .agg(med_rho=("rho", "median"), med_wall=("wall_time_s", "median"), med_wh=("energy_wh", "median"))
        .reset_index()
    )
    style_map = {t[0]: (t[1], t[3], t[4]) for t in TOOL_META}
    highlights = {
        ("aequilibrae", "aon"): ("Aeq AoN", (7, -10)),
        ("aequilibrae", "ue_bfw"): ("Aeq UE", (7, -2)),
        ("cityseer_od", "default"): ("cityseer", (-44, 10)),
        ("una", "shortest"): ("UNA short", (7, -11)),
        ("sdna", "nqpd_euclidean"): ("sDNA NQPD", (7, -10)),
        ("sdna", "betweenness_euclidean"): ("sDNA Bt", (-56, 7)),
        ("sdna", "mode_hybrid"): ("sDNA hybrid", (-66, -6)),
    }
    for _, r in vstats.iterrows():
        t, v = r["tool"], r["variant"]
        _, marker, color = style_map[t]
        is_hi = (t, v) in highlights
        ax2.scatter(
            r["med_wall"],
            r["med_rho"],
            s=58 if is_hi else 28,
            marker=marker,
            color=color,
            alpha=0.95 if is_hi else 0.4,
            edgecolor="white",
            lw=0.7,
            zorder=4 if is_hi else 2,
        )
        if is_hi:
            lbl, (dx, dy) = highlights[(t, v)]
            wh_txt = format_wh(r["med_wh"])
            ax2.annotate(
                f"{lbl}\n({wh_txt} Wh)",
                (r["med_wall"], r["med_rho"]),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=6.8,
                color="#2c2c2a",
                linespacing=1.1,
            )

    ax2.set_xscale("log")
    ax2.set_xlim(8, 1600)
    ax2.set_ylim(0.66, 0.825)
    ax2.set_xlabel("Median wall time per city (s, log scale)", fontsize=8.5, color="#333333")
    ax2.set_ylabel("Car median Spearman $\\rho$", fontsize=8.5, color="#333333")
    ax2.set_title("(b) Car accuracy vs speed & energy", fontsize=9.5, loc="left", fontweight="bold", color="#222222")
    ax2.grid(color="#eaeae6", lw=0.7, zorder=0)

    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(labelsize=8, colors="#333333")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=1.2)
    fig.savefig(out_path, dpi=160, facecolor="white")
    plt.close(fig)


def update_readme(readme_path: Path, table_md: str, check: bool = False) -> bool:
    text = readme_path.read_text()
    if START_MARKER not in text or END_MARKER not in text:
        raise ValueError(f"{readme_path} must contain {START_MARKER} and {END_MARKER}")
    pre, rest = text.split(START_MARKER, 1)
    _, post = rest.split(END_MARKER, 1)
    updated = f"{pre}{START_MARKER}\n{table_md}\n{END_MARKER}{post}"
    if updated == text:
        return False
    if not check:
        readme_path.write_text(updated)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--readme", type=Path, default=DEFAULT_README)
    ap.add_argument("--figure", type=Path, default=DEFAULT_FIG)
    ap.add_argument("--no-readme", action="store_true")
    ap.add_argument("--check", action="store_true", help="Exit 1 if README table is out of date.")
    args = ap.parse_args()

    df = load_board(args.csv)
    table_md = build_markdown_table(df)
    if not args.check:
        build_hero_figure(df, args.figure)
    if not args.no_readme:
        changed = update_readme(args.readme, table_md, check=args.check)
        if args.check and changed:
            print("README.md leaderboard block is out of date. Run scripts/update_readme_results.py.")
            return 1
    else:
        print(table_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
