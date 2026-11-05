The submission is a droop-plus-PI voltage-loop model. It parses, starts at rest, and beats the flat baseline on every validation check, though its open-loop Q error on the load recording (0.016 against a flat 0.028) is the weakest result.

**Model** (internal frame at angle `delta`, with `vd = V·cos(delta−θ)`, `vq = −V·sin(delta−θ)`):

- **Active power:** `Pe = vd·Id + vq·Iq`, filtered by `Pf` with a time constant `Tf`. Frequency droop: `d(delta)/dt = w0·m·(P0 − Pf)`, so the internal angle moves with the active-power error. The fit gives `m ≈ 0.059`.
- **Reactive power:** `Qe = −vd·Iq + vq·Id`, filtered by `Qf`. The reference is `vr = Vset + n·(Q0 − Qf)`, a reactive droop with `n ≈ 0.028`.
- **Voltage loop:** a PI loop with `Id = Kpv·(vr − vd) + xvd` and `Iq = −Kpv·vq + xvq`, where `xvd` and `xvq` integrate `Kiv` times the same errors. Current follows its reference at once (ideal inner loop). The fit gives `Kpv ≈ 0.68` and `Kiv ≈ 1.18`.
- **Outputs:** `P = Pe`, `Q = Qe`.

**Identification:**
- `m`, `n`, `Kpv` and `Kiv` are reasonably determined by the staged voltage steps and the generator and load events. The fit cost was still falling slightly at the last call, so these are close to, but not fully at, a minimum.
- `Tf` went to about 1e-6, so the active-power filter is effectively off. The fit could not resolve any measurable lag in P.
- `n` is small and trades off against `Kpv` and `Kiv`. Its value is less certain than `m`.
- The simpler voltage-behind-reactance structure fit poorly (0.38 of flat error, with reactive droop driven to zero), so I did not use it.

```json
{
  "params": {
    "Tf": 9.372476831916957e-07,
    "m": 0.0591911491593823,
    "n": 0.027647926736724036,
    "Kpv": 0.682665241457403,
    "Kiv": 1.1809427242438746,
    "w0": 376.99111843077515
  },
  "defs": {
    "vd": "V*cos(delta - theta)",
    "vq": "-V*sin(delta - theta)",
    "vr": "Vset + n*(Q0 - Qf)",
    "Idref": "Kpv*(vr - vd) + xvd",
    "Iqref": "Kpv*(0 - vq) + xvq",
    "Id": "Idref",
    "Iq": "Iqref",
    "Pe": "vd*Id + vq*Iq",
    "Qe": "-vd*Iq + vq*Id"
  },
  "states": {
    "Pf": {
      "rhs": "(Pe - Pf)/Tf",
      "init": "P0"
    },
    "Qf": {
      "rhs": "(Qe - Qf)/Tf",
      "init": "Q0"
    },
    "delta": {
      "rhs": "w0*m*(P0 - Pf)",
      "init": "theta0"
    },
    "xvd": {
      "rhs": "Kiv*(vr - vd)",
      "init": "P0/V0"
    },
    "xvq": {
      "rhs": "Kiv*(0 - vq)",
      "init": "-Q0/V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qe"
  }
}
```