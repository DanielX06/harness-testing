"""One-line diagrams of the test grids.

    python test_cases/draw_grid_diagrams.py      # grid_A/sandbox_data/system_diagram.png (the solver's copy: no case
                                                 #   or model names), grid_B/holdout/system_diagram.png (for you; the
                                                 #   solver never sees B), grid_M/holdout/system_diagram.png (for you)
    python test_cases/draw_grid_diagrams.py M    # only the grids named (A, B, M), e.g. to leave the solver's copy alone

The labels below are written by hand from each grid's spec (grid_specs/), so change them when a grid changes.
make_noise_free_sandbox.py copies grid A's diagram into sandbox_data_clean/; run it after redrawing grid A.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch            # noqa: E402

TEST_CASES_DIR = Path(__file__).resolve().parent
INK_COLOR, MUTED_COLOR, OUT_OF_SERVICE_COLOR, DEVICE_COLOR = "#1a1a19", "#6b6a63", "#c4441a", "#3a9a5b"
BUS_X = {1: 0.0, 5: 1.6, 6: 3.3, 7: 5.0, 8: 9.6, 9: 11.3, 10: 13.0, 4: 14.6}    # buses left to right
MAIN_ROW_Y = 3.0


def draw_grid(grid):
    figure, axis = plt.subplots(figsize=(16, 7.6))
    axis.set_xlim(-2.3, 16.9); axis.set_ylim(-2.4, 5.7); axis.set_aspect("equal"); axis.axis("off")

    def draw_bus(x, y, number, half_height=0.55):
        axis.plot([x, x], [y - half_height, y + half_height], color=INK_COLOR, lw=3.5, solid_capstyle="butt")
        axis.text(x + 0.08, y + half_height + 0.08, str(number), fontsize=11, color=INK_COLOR, ha="left", va="bottom",
                  weight="bold")

    def draw_circuits(x_from, x_to, y, count, label=None, out_of_service=0):
        for index in range(count):
            offset = (index - (count - 1) / 2) * 0.13
            out = index < out_of_service
            axis.plot([x_from, x_to], [y + offset, y + offset], color=OUT_OF_SERVICE_COLOR if out else INK_COLOR, lw=1.4,
                      ls="--" if out else "-")
        if label:
            axis.text((x_from + x_to) / 2, y + 0.13 * count / 2 + 0.12, label, ha="center", fontsize=8.5, color=MUTED_COLOR)

    def draw_generator(x, y, name, dispatch):
        axis.add_patch(Circle((x, y), 0.36, fill=False, ec=INK_COLOR, lw=1.8))
        axis.text(x, y, "~", ha="center", va="center", fontsize=18, color=INK_COLOR)
        axis.text(x, y - 0.55, name, ha="center", va="top", fontsize=10, color=INK_COLOR, weight="bold")
        axis.text(x, y - 0.85, dispatch, ha="center", va="top", fontsize=8.5, color=MUTED_COLOR)

    def draw_load(x, y, label, label_on_left=False):
        axis.annotate("", xy=(x, y - 0.75), xytext=(x, y), arrowprops=dict(arrowstyle="-|>", color=INK_COLOR, lw=1.6))
        axis.text(x - 0.12 if label_on_left else x + 0.12, y - 0.55, label, fontsize=8.5, color=MUTED_COLOR, va="center",
                  ha="right" if label_on_left else "left")

    draw_circuits(BUS_X[1], BUS_X[5], MAIN_ROW_Y, 1)
    draw_circuits(BUS_X[5], BUS_X[6], MAIN_ROW_Y, 2, grid.get("label_5_6", "2 circuits"),
                  out_of_service=grid.get("out_of_service_5_6", 0))
    draw_circuits(BUS_X[6], BUS_X[7], MAIN_ROW_Y, 2, "2 circuits")
    draw_circuits(BUS_X[7], BUS_X[8], MAIN_ROW_Y, 3, grid["tie_label"], out_of_service=grid.get("tie_out_of_service", 0))
    draw_circuits(BUS_X[8], BUS_X[9], MAIN_ROW_Y, 2, "2 circuits")
    draw_circuits(BUS_X[9], BUS_X[10], MAIN_ROW_Y, 2, "2 circuits")
    draw_circuits(BUS_X[10], BUS_X[4], MAIN_ROW_Y, 1)
    for bus in (1, 5, 6, 7, 8, 9, 10, 4):
        draw_bus(BUS_X[bus], MAIN_ROW_Y, bus)
    axis.plot([BUS_X[1] - 0.9, BUS_X[1]], [MAIN_ROW_Y, MAIN_ROW_Y], color=INK_COLOR, lw=1.4)
    draw_generator(BUS_X[1] - 1.26, MAIN_ROW_Y, "G1", "slack")
    axis.plot([BUS_X[4], BUS_X[4] + 0.9], [MAIN_ROW_Y, MAIN_ROW_Y], color=INK_COLOR, lw=1.4)
    draw_generator(BUS_X[4] + 1.26, MAIN_ROW_Y, "G4", grid["g4"])
    axis.plot([BUS_X[6], BUS_X[6]], [MAIN_ROW_Y - 0.55, 1.5], color=INK_COLOR, lw=1.4)        # generator 2 below bus 6
    axis.plot([BUS_X[6] - 0.35, BUS_X[6] + 0.35], [1.2, 1.2], color=INK_COLOR, lw=3.5)
    axis.text(BUS_X[6] + 0.42, 1.2, "2", fontsize=11, weight="bold", va="center")
    axis.plot([BUS_X[6], BUS_X[6]], [1.2, 0.75], color=INK_COLOR, lw=1.4)
    draw_generator(BUS_X[6], 0.39, "G2", grid["g2"])

    axis.plot([BUS_X[9], BUS_X[9]], [MAIN_ROW_Y - 0.55, 1.5], color=DEVICE_COLOR, lw=1.6)    # the device below bus 9
    axis.plot([BUS_X[9] - 0.35, BUS_X[9] + 0.35], [1.2, 1.2], color=INK_COLOR, lw=3.5)
    axis.text(BUS_X[9] + 0.42, 1.2, "3", fontsize=11, weight="bold", va="center")
    axis.plot([BUS_X[9], BUS_X[9]], [1.2, 0.8], color=DEVICE_COLOR, lw=1.6)
    axis.add_patch(FancyBboxPatch((BUS_X[9] - 0.95, -0.1), 1.9, 0.9, boxstyle="round,pad=0.05", fc="#e8f4ec",
                                  ec=DEVICE_COLOR, lw=1.8))
    axis.text(BUS_X[9], 0.5, "Inverter-based\nunit", ha="center", va="center", fontsize=9, color=DEVICE_COLOR, weight="bold")
    axis.text(BUS_X[9], -0.25, grid["device"], ha="center", va="top", fontsize=8.5, color=DEVICE_COLOR)
    axis.text(BUS_X[9] + 1.15, 0.35, "measured at bus 3:\nP, Q, V, θ\n+ voltage setpoint log", fontsize=8.5,
              color=DEVICE_COLOR, va="center")
    for bus, label in grid["loads"].items():
        draw_load(BUS_X[bus], MAIN_ROW_Y - 0.55, label, label_on_left=(bus == 9))
    for x_from, x_to, name in ((BUS_X[1] - 1.9, BUS_X[7] + 0.3, "Area 1"), (BUS_X[8] - 0.3, BUS_X[4] + 1.9, "Area 2")):
        axis.plot([x_from, x_from, x_to, x_to], [5.0, 5.15, 5.15, 5.0], color=MUTED_COLOR, lw=1)
        axis.text((x_from + x_to) / 2, 5.25, name, ha="center", fontsize=11, color=INK_COLOR)
    for index, line in enumerate(grid["notes"]):
        axis.text(-2.2, -1.55 - 0.32 * index, line, fontsize=9, color=MUTED_COLOR if index else INK_COLOR)
    figure.savefig(grid["out"], dpi=150, bbox_inches="tight")
    plt.close(figure)
    print(grid["out"])


GRID_A = dict(
    tie_label="tie line, 3 circuits", g2="400 MW", g4="700 MW (800 MW at op2)",
    device="900 MVA\n700 MW (450 MW at op2)",
    loads={7: "L7  859 MW", 8: "L8  1425 MW\n(1525 MW at op3)", 10: "L10  150 MW"},
    notes=["Ten-bus, two-area system; transformers between buses 1-5, 2-6, 3-9 and 4-10. Operating points (see runs.json):",
           "op1 as drawn, voltage schedule 1.00 pu.  op2: unit at 450 MW, schedule 1.01 pu, G4 at 800 MW.  "
           "op3: one 9-10 circuit out of service, L8 +100 MW."],
    out=TEST_CASES_DIR / "grid_A" / "sandbox_data" / "system_diagram.png")
GRID_B = dict(
    tie_label="tie line, 2 of 3 circuits in service (dashed: out)", tie_out_of_service=1, g2="400 MW", g4="700 MW",
    device="900 MVA, 720 MW\nvoltage schedule 1.02 pu",
    loads={7: "L7  900 MW", 8: "L8  1200 MW", 9: "L9  200 MW (new)", 10: "L10  150 MW"},
    notes=["Grid B (selection, never shown to the agent): Kundur re-arranged. One 7-8 tie circuit out, a new load at the "
           "unit's HV bus 9, 225 MW of load moved from bus 8 to bus 7, unit at 720 MW.",
           "Held-out runs at t = 2 s, 25 s each: voltage-reference step +2.5% (back at 14 s); L9 +50%; one 8-9 circuit trips."],
    out=TEST_CASES_DIR / "grid_B" / "holdout" / "system_diagram.png")
GRID_M = dict(
    tie_label="tie line, 3 circuits", label_5_6="1 of 2 in service", out_of_service_5_6=1, g2="500 MW", g4="650 MW",
    device="900 MVA, 650 MW\nvoltage schedule 1.01 pu",
    loads={7: "L7  1000 MW", 8: "L8  1150 MW", 10: "L10  300 MW"},
    notes=["Grid M (hidden monitor: selects nothing, never shown to the agent or the updater): Kundur re-arranged another "
           "way. One 5-6 circuit out (dashed), L10 doubled to 300 MW, G2 at 500 MW, unit at 650 MW.",
           "Held-out runs at t = 2 s, 25 s each: voltage-reference step -1.5% (back at 14 s); L10 -40%; one 6-7 circuit trips."],
    out=TEST_CASES_DIR / "grid_M" / "holdout" / "system_diagram.png")
GRIDS = {"A": GRID_A, "B": GRID_B, "M": GRID_M}

if __name__ == "__main__":
    for key in sys.argv[1:] or GRIDS:
        draw_grid(GRIDS[key.upper()])
