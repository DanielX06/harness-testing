"""One-line diagrams of the test grids.

    python test_cases/draw_grid_diagrams.py      # grid_A/sandbox_data/system_diagram.png (the solver's copy: no case
                                                 #   or model names), grid_B/holdout/system_diagram.png (for you; the
                                                 #   solver never sees B), grid_M/holdout/system_diagram.png (for you)
    python test_cases/draw_grid_diagrams.py M    # only the grids named (A, B, M, A2, B2, M2), e.g. to leave the solver's copy alone

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

    # circuits out of service per corridor: grid["circuits_out"] (random grids), else the hand-written keys
    out = dict(grid.get("circuits_out", {}))
    out.setdefault("5-6", grid.get("out_of_service_5_6", 0))
    out.setdefault("7-8", grid.get("tie_out_of_service", 0))

    def corridor_label(name, count, default):
        if name in grid.get("labels", {}):
            return grid["labels"][name]
        if not out.get(name):
            return default
        return f"{count - out[name]} of {count} in service"            # the dashed circuit is out
    draw_circuits(BUS_X[1], BUS_X[5], MAIN_ROW_Y, 1)
    draw_circuits(BUS_X[5], BUS_X[6], MAIN_ROW_Y, 2, grid.get("label_5_6") or corridor_label("5-6", 2, "2 circuits"),
                  out_of_service=out.get("5-6", 0))
    draw_circuits(BUS_X[6], BUS_X[7], MAIN_ROW_Y, 2, corridor_label("6-7", 2, "2 circuits"), out_of_service=out.get("6-7", 0))
    draw_circuits(BUS_X[7], BUS_X[8], MAIN_ROW_Y, 3, grid.get("tie_label") or corridor_label("7-8", 3, "tie line, 3 circuits"),
                  out_of_service=out.get("7-8", 0))
    draw_circuits(BUS_X[8], BUS_X[9], MAIN_ROW_Y, 2, corridor_label("8-9", 2, "2 circuits"), out_of_service=out.get("8-9", 0))
    draw_circuits(BUS_X[9], BUS_X[10], MAIN_ROW_Y, 2, corridor_label("9-10", 2, "2 circuits"), out_of_service=out.get("9-10", 0))
    draw_circuits(BUS_X[10], BUS_X[4], MAIN_ROW_Y, 1)
    for bus in (1, 5, 6, 7, 8, 9, 10, 4):
        draw_bus(BUS_X[bus], MAIN_ROW_Y, bus)
    axis.plot([BUS_X[1] - 0.9, BUS_X[1]], [MAIN_ROW_Y, MAIN_ROW_Y], color=INK_COLOR, lw=1.4)
    draw_generator(BUS_X[1] - 1.26, MAIN_ROW_Y, "G1", "slack")
    # the machines: G2 hangs below bus 6 (its own bus 2), G3 below bus 9 (bus 3), G4 to the right of bus 4.
    # The inverter-based unit takes one of those slots (grid["device_slot"], default 3, as in every fixed grid).
    slot = int(grid.get("device_slot", 3))

    def draw_hanging_bus(x, number, color):
        axis.plot([x, x], [MAIN_ROW_Y - 0.55, 1.5], color=color, lw=1.6 if color == DEVICE_COLOR else 1.4)
        axis.plot([x - 0.35, x + 0.35], [1.2, 1.2], color=INK_COLOR, lw=3.5)
        axis.text(x + 0.42, 1.2, str(number), fontsize=11, weight="bold", va="center")

    def draw_device(x, top, terminal_bus, text_side):
        axis.plot([x, x], [top, 0.8], color=DEVICE_COLOR, lw=1.6)
        axis.add_patch(FancyBboxPatch((x - 0.95, -0.1), 1.9, 0.9, boxstyle="round,pad=0.05", fc="#e8f4ec",
                                      ec=DEVICE_COLOR, lw=1.8))
        axis.text(x, 0.5, "Inverter-based\nunit", ha="center", va="center", fontsize=9, color=DEVICE_COLOR, weight="bold")
        axis.text(x, -0.25, grid["device"], ha="center", va="top", fontsize=8.5, color=DEVICE_COLOR)
        axis.text(x + 1.15 * text_side, 0.35, f"measured at bus {terminal_bus}:\nP, Q, V, θ\n+ voltage setpoint log",
                  fontsize=8.5, color=DEVICE_COLOR, va="center", ha="left" if text_side > 0 else "right")

    for machine, bus_x in ((2, BUS_X[6]), (3, BUS_X[9])):
        draw_hanging_bus(bus_x, machine, DEVICE_COLOR if machine == slot else INK_COLOR)
        if machine == slot:
            draw_device(bus_x, 1.2, machine, +1 if machine == 3 else -1)
        else:
            axis.plot([bus_x, bus_x], [1.2, 0.75], color=INK_COLOR, lw=1.4)
            draw_generator(bus_x, 0.39, f"G{machine}", grid[f"g{machine}"])
    if slot == 4:
        axis.plot([BUS_X[4], BUS_X[4]], [MAIN_ROW_Y - 0.55, 1.2], color=DEVICE_COLOR, lw=1.6)
        draw_device(BUS_X[4], 1.2, 4, +1)
    else:
        axis.plot([BUS_X[4], BUS_X[4] + 0.9], [MAIN_ROW_Y, MAIN_ROW_Y], color=INK_COLOR, lw=1.4)
        draw_generator(BUS_X[4] + 1.26, MAIN_ROW_Y, "G4", grid["g4"])
    for bus, label in grid["loads"].items():
        if bus == 9 and "device_slot" in grid:       # random grids: beside the line down to bus 3, clear of L8's label
            draw_load(BUS_X[bus] + 0.3, MAIN_ROW_Y - 0.55, label)
        else:
            draw_load(BUS_X[bus], MAIN_ROW_Y - 0.55, label, label_on_left=(bus == 9))
    for x_from, x_to, name in ((BUS_X[1] - 1.9, BUS_X[7] + 0.3, "Area 1"), (BUS_X[8] - 0.3, BUS_X[4] + 1.9, "Area 2")):
        axis.plot([x_from, x_from, x_to, x_to], [5.0, 5.15, 5.15, 5.0], color=MUTED_COLOR, lw=1)
        axis.text((x_from + x_to) / 2, 5.25, name, ha="center", fontsize=11, color=INK_COLOR)
    for index, line in enumerate(grid["notes"]):
        axis.text(-2.2, -1.55 - 0.32 * index, line, fontsize=9, color=MUTED_COLOR if index else INK_COLOR)
    Path(grid["out"]).parent.mkdir(parents=True, exist_ok=True)
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
# grids A2, B2 and M2 are A, B and M with the REGF2 unit in the slot: the same drawings (A2's is the solver's copy)
GRID_A2 = dict(GRID_A, out=TEST_CASES_DIR / "grid_A2" / "sandbox_data" / "system_diagram.png")
GRID_B2 = dict(GRID_B, out=TEST_CASES_DIR / "grid_B2" / "holdout" / "system_diagram.png")
GRID_M2 = dict(GRID_M, out=TEST_CASES_DIR / "grid_M2" / "holdout" / "system_diagram.png")
# and A3, B3 and M3 the same with the REGF3 unit (the held-out device)
GRID_A3 = dict(GRID_A, out=TEST_CASES_DIR / "grid_A3" / "sandbox_data" / "system_diagram.png")
GRID_B3 = dict(GRID_B, out=TEST_CASES_DIR / "grid_B3" / "holdout" / "system_diagram.png")
GRID_M3 = dict(GRID_M, out=TEST_CASES_DIR / "grid_M3" / "holdout" / "system_diagram.png")
GRIDS = {"A": GRID_A, "B": GRID_B, "M": GRID_M, "A2": GRID_A2, "B2": GRID_B2, "M2": GRID_M2,
         "A3": GRID_A3, "B3": GRID_B3, "M3": GRID_M3}

if __name__ == "__main__":
    for key in sys.argv[1:] or ("A", "B", "M"):
        draw_grid(GRIDS[key.upper()])
