"""One-line diagrams of the test-case grids.

    python draw_grids.py      # grid_A/sandbox_data/system_diagram.png (agent copy: no case or model names)
                              # grid_B/holdout/system_diagram.png      (for you; the agent never sees B)
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch            # noqa: E402

HERE = Path(__file__).resolve().parent
INK, MUTED, OUT, DEV, NOTE = "#1a1a19", "#6b6a63", "#c4441a", "#3a9a5b", "#2a78d6"
X = {1: 0.0, 5: 1.6, 6: 3.3, 7: 5.0, 8: 9.6, 9: 11.3, 10: 13.0, 4: 14.6}
Y0 = 3.0


def draw(g):
    fig, ax = plt.subplots(figsize=(16, 7.6))
    ax.set_xlim(-2.3, 16.9); ax.set_ylim(-2.4, 5.7); ax.set_aspect("equal"); ax.axis("off")

    def bus(x, y, n, h=0.55):
        ax.plot([x, x], [y - h, y + h], color=INK, lw=3.5, solid_capstyle="butt")
        ax.text(x + 0.08, y + h + 0.08, str(n), fontsize=11, color=INK, ha="left", va="bottom", weight="bold")

    def lines(xa, xb, y, k, label=None, out=0):
        for i in range(k):
            dy = (i - (k - 1) / 2) * 0.13
            c = OUT if i < out else INK
            ax.plot([xa, xb], [y + dy, y + dy], color=c, lw=1.4, ls="--" if i < out else "-")
        if label:
            ax.text((xa + xb) / 2, y + 0.13 * k / 2 + 0.12, label, ha="center", fontsize=8.5, color=MUTED)

    def gen(x, y, name, sub):
        ax.add_patch(Circle((x, y), 0.36, fill=False, ec=INK, lw=1.8))
        ax.text(x, y, "~", ha="center", va="center", fontsize=18, color=INK)
        ax.text(x, y - 0.55, name, ha="center", va="top", fontsize=10, color=INK, weight="bold")
        ax.text(x, y - 0.85, sub, ha="center", va="top", fontsize=8.5, color=MUTED)

    def load(x, y, label, left=False):
        ax.annotate("", xy=(x, y - 0.75), xytext=(x, y), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.6))
        ax.text(x - 0.12 if left else x + 0.12, y - 0.55, label, fontsize=8.5, color=MUTED, va="center",
                ha="right" if left else "left")

    lines(X[1], X[5], Y0, 1)
    lines(X[5], X[6], Y0, 2, "2 circuits")
    lines(X[6], X[7], Y0, 2, "2 circuits")
    lines(X[7], X[8], Y0, 3, g["tie_label"], out=g.get("tie_out", 0))
    lines(X[8], X[9], Y0, 2, "2 circuits")
    lines(X[9], X[10], Y0, 2, "2 circuits")
    lines(X[10], X[4], Y0, 1)
    for b in (1, 5, 6, 7, 8, 9, 10, 4):
        bus(X[b], Y0, b)
    ax.plot([X[1] - 0.9, X[1]], [Y0, Y0], color=INK, lw=1.4)
    gen(X[1] - 1.26, Y0, "G1", "slack")
    ax.plot([X[4], X[4] + 0.9], [Y0, Y0], color=INK, lw=1.4)
    gen(X[4] + 1.26, Y0, "G4", g["g4"])
    ax.plot([X[6], X[6]], [Y0 - 0.55, 1.5], color=INK, lw=1.4)
    ax.plot([X[6] - 0.35, X[6] + 0.35], [1.2, 1.2], color=INK, lw=3.5)
    ax.text(X[6] + 0.42, 1.2, "2", fontsize=11, weight="bold", va="center")
    ax.plot([X[6], X[6]], [1.2, 0.75], color=INK, lw=1.4)
    gen(X[6], 0.39, "G2", g["g2"])

    ax.plot([X[9], X[9]], [Y0 - 0.55, 1.5], color=DEV, lw=1.6)
    ax.plot([X[9] - 0.35, X[9] + 0.35], [1.2, 1.2], color=INK, lw=3.5)
    ax.text(X[9] + 0.42, 1.2, "3", fontsize=11, weight="bold", va="center")
    ax.plot([X[9], X[9]], [1.2, 0.8], color=DEV, lw=1.6)
    ax.add_patch(FancyBboxPatch((X[9] - 0.95, -0.1), 1.9, 0.9, boxstyle="round,pad=0.05", fc="#e8f4ec", ec=DEV, lw=1.8))
    ax.text(X[9], 0.5, "Inverter-based\nunit", ha="center", va="center", fontsize=9, color=DEV, weight="bold")
    ax.text(X[9], -0.25, g["dev"], ha="center", va="top", fontsize=8.5, color=DEV)
    ax.text(X[9] + 1.15, 0.35, "measured at bus 3:\nP, Q, V, θ\n+ voltage setpoint log", fontsize=8.5, color=DEV, va="center")
    for b, lab in g["loads"].items():
        load(X[b], Y0 - 0.55, lab, left=(b == 9))
    for xa, xb, name in ((X[1] - 1.9, X[7] + 0.3, "Area 1"), (X[8] - 0.3, X[4] + 1.9, "Area 2")):
        ax.plot([xa, xa, xb, xb], [5.0, 5.15, 5.15, 5.0], color=MUTED, lw=1)
        ax.text((xa + xb) / 2, 5.25, name, ha="center", fontsize=11, color=INK)
    for i, line in enumerate(g["notes"]):
        ax.text(-2.2, -1.55 - 0.32 * i, line, fontsize=9, color=MUTED if i else INK)
    fig.savefig(g["out"], dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(g["out"])


GRID_A = dict(
    tie_label="tie line, 3 circuits", g2="400 MW", g4="700 MW (800 MW at op2)",
    dev="900 MVA\n700 MW (450 MW at op2)",
    loads={7: "L7  859 MW", 8: "L8  1425 MW\n(1525 MW at op3)", 10: "L10  150 MW"},
    notes=["Ten-bus, two-area system; transformers between buses 1-5, 2-6, 3-9 and 4-10. Operating points (see runs.json):",
           "op1 as drawn, voltage schedule 1.00 pu.  op2: unit at 450 MW, schedule 1.01 pu, G4 at 800 MW.  "
           "op3: one 9-10 circuit out of service, L8 +100 MW."],
    out=HERE / "grid_A" / "sandbox_data" / "system_diagram.png")
GRID_B = dict(
    tie_label="tie line, 2 of 3 circuits in service (dashed: out)", tie_out=1, g2="400 MW", g4="700 MW",
    dev="900 MVA, 720 MW\nvoltage schedule 1.02 pu",
    loads={7: "L7  900 MW", 8: "L8  1200 MW", 9: "L9  200 MW (new)", 10: "L10  150 MW"},
    notes=["Grid B (selection, never shown to the agent): Kundur re-arranged. One 7-8 tie circuit out, a new load at the "
           "unit's HV bus 9, 225 MW of load moved from bus 8 to bus 7, unit at 720 MW.",
           "Held-out runs at t = 2 s, 25 s each: voltage-reference step +2.5% (back at 14 s); L9 +50%; one 8-9 circuit trips."],
    out=HERE / "grid_B" / "holdout" / "system_diagram.png")

if __name__ == "__main__":
    for g in (GRID_A, GRID_B):
        draw(g)
