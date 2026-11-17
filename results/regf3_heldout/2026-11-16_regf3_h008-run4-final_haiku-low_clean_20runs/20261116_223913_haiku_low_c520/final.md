I'm stopping here and submitting the best candidate I have, c2, which is already saved as `submission.json`. It passes the scorer's rest-state check on both validation files, but it is a weak model for Q and its parameters are degenerate, so treat it as provisional.

**Submitted model (c2)**: a droop-type grid-forming model. The P path is a P-f droop with a frequency-driven internal angle and a 1 ms measurement filter; the Q path is an electrical coupling with a very large reactance.

- `delta' = w0·mp·(P0 − Pm)`, with `Pm` filtered from `Pe`.
- `Ei = xv + kff·(Vset − V0)`, with `xv` an integrator (its rate is `kiv·(Vcmd − Vm)`).
- `Pe = V·XL·Ei·sin(delta − theta)/XL²`, `Qe = V·(XL·(Ei·cos(delta − theta) − V))/XL²` (Re = 0).
- Fitted values: XL ≈ 64.6, mp ≈ 0.0525, kff ≈ 0.173.

**Identification status**
- **mp (P-f droop)**: well identified. The ambient and load-step data give a frequency-to-P sensitivity of about −18 pu/pu, consistent with mp ≈ 0.05. P error on validation is 0.06–0.10.
- **kff (setpoint feed-forward)**: moderately identified. It is the only route by which the setpoint reaches Q.
- **XL**: poorly identified. The fit pushed it to 64, far outside the normal range, so it is acting as a numerical device to make Q nearly insensitive to V. It is not a physical reactance.
- **mq, kiv, TVf, TQf**: not identified. The optimiser drove them to degenerate extremes (mq ≈ 7e21, TVf ≈ 5e108, kiv ≈ 2e-19). Their product mq·kiv is large, so the voltage loop is effectively unobservable in this fit, and I did not manage to replace it with a clean structure.
- **Q overall**: poorly fitted. The observed Q moves by only about 0.0005 in ambient operation and barely responds to V or the setpoint. Q errors on validation are 0.53 (load recording) and 0.78 (vref recording). A simple first-order filter on V and Vset did not explain Q (residual ≈0.96). Cleaning up the degenerate voltage loop (setting mq and kiv to zero) made Q much worse (errors 4–16), so I did not keep it.

**Other limits**
- Mean validation error is 0.367. Most of that comes from Q.
- The model passed the stability check, but its stability depends on the degenerate large-mq/kiv combination, so it may be fragile on the scorer's held-out disturbances.
- I did not get to fit the fault recording; it is excluded by the tool and was not used.

```json
{
  "params": {
    "XL": 64.59366309083187,
    "Re": 0.0,
    "mp": 0.05251400924473359,
    "mq": 7.155569589199914e+21,
    "kpv": 0.0,
    "kiv": 2.4541830511306188e-19,
    "kff": 0.17324580906176523,
    "TPf": 0.0009999999999994458,
    "TQf": 0.0009999999999994458,
    "TVf": 5.239644028692858e+108,
    "w0": 376.99111843077515
  },
  "defs": {
    "Vcmd": "Vset + mq*(Q0 - Qm)",
    "Ei": "xv + kpv*(Vcmd - Vm) + kff*(Vset - V0)",
    "dl": "delta - theta",
    "Pe": "V*(Re*(Ei*cos(dl) - V) + XL*Ei*sin(dl))/(Re**2 + XL**2)",
    "Qe": "V*(XL*(Ei*cos(dl) - V) - Re*Ei*sin(dl))/(Re**2 + XL**2)"
  },
  "states": {
    "delta": {
      "rhs": "w0*mp*(P0 - Pm)",
      "init": "theta0 + atan2((XL*P0 - Re*Q0)/V0, V0 + (Re*P0 + XL*Q0)/V0)"
    },
    "xv": {
      "rhs": "kiv*(Vcmd - Vm)",
      "init": "sqrt((V0 + (Re*P0 + XL*Q0)/V0)**2 + ((XL*P0 - Re*Q0)/V0)**2)"
    },
    "Pm": {
      "rhs": "(Pe - Pm)/TPf",
      "init": "P0"
    },
    "Qm": {
      "rhs": "(Qe - Qm)/TQf",
      "init": "Q0"
    },
    "Vm": {
      "rhs": "(V - Vm)/TVf",
      "init": "V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qe"
  }
}
```