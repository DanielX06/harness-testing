WHAT IS KNOWN ABOUT THE DEVICE AND THE GRID (operator documentation)
- The device is a grid-forming inverter-based unit rated 900 MVA. Its terminal is bus 3, which connects to bus 9 through its step-up transformer (see system_diagram.png).
- Its documentation says it supports grid frequency through active-power droop and regulates voltage through reactive-power droop. It does not say which grid-forming control it uses, or its gains, limits and time constants. Identifying its terminal behaviour is the task.
- The operator sets its active-power dispatch and its voltage schedule. runs.json gives both for each recording, and voltage_setpoint_pu logs the setpoint over time. How the setpoint enters the unit's control is not documented; at t = 0 it equals V0.
- The rest of the network is a ten-bus, two-area system with three synchronous generators, each with a governor and an exciter. Loads are constant impedance, so their P and Q scale with V squared. No secondary control restores frequency, so after an event the frequency can settle away from nominal and the bus angle keeps drifting.
- Short-circuit study at the device terminal: at short time scales (tens of milliseconds) the rest of the network, seen from bus 3, behaves like a voltage source behind about 0.5 pu reactance on the device's 900 MVA rating (short-circuit ratio about 2). Slower behaviour (the generators' controls, machines swinging against each other) is not part of that equivalent.

REFERENCE: THE WECC GENERIC GRID-FORMING MODELS
The Western Electricity Coordinating Council has approved two generic positive-sequence models of grid-forming units for planning studies: a droop-controlled model (PNNL-35110, September 2023) and a virtual synchronous machine model (NREL/TP-5D00-90260, June 2024). Their block diagrams are written out below as equations. They are generic models: a vendor's unit can differ from both in structure, limits, filtering and inner loops, so treat them as a guide to what such controls look like, not as this unit's documentation.

Conventions used below
- V and theta are the terminal voltage magnitude (pu) and angle (rad); P and Q are the power the unit injects at the terminal, in pu on its 900 MVA rating. The specifications convert from the network's base to the unit's rating; here that factor is 1.
- w0 = 2*pi*60 = 376.99 rad/s. Frequencies inside the controllers are in pu of nominal unless a w0 multiplies them.
- clip(x, lo, hi) means min(max(x, lo), hi). "x held in [lo, hi]" means an integrator that stops at its limits (no windup).
- Both models are a voltage source E at angle delta behind a coupling impedance Re + j*XL. delta is an absolute angle, like theta. At the terminal:
    P = V*(Re*(E*cos(delta - theta) - V) + XL*E*sin(delta - theta)) / (Re^2 + XL^2)
    Q = V*(XL*(E*cos(delta - theta) - V) - Re*E*sin(delta - theta)) / (Re^2 + XL^2)
  With Re = 0 these are P = E*V*sin(delta - theta)/XL and Q = (E*V*cos(delta - theta) - V^2)/XL.
- Transient current limit (both models): the current is I = (E at delta - V at theta)/(Re + j*XL). While |I| < ImaxF the source is as above. When |I| would reach ImaxF (severe faults), the source is replaced by V at theta plus (Re + j*XL)*ImaxF at the current's own angle, so the magnitude is held at ImaxF and the angle is kept. It switches back once the fault clears.

Droop-controlled model
Measurement filters:
    d(Pm)/dt = (P - Pm)/TPf        d(Qm)/dt = (Q - Qm)/TQf        d(Vm)/dt = (V - Vm)/TVf
P-f droop, with overload mitigation that keeps P between Pmin and Pmax:
    dw = w0*(mp*(Pref - Pm) + uPmax + uPmin)                 (rad/s)
    d(delta)/dt = dw                                         (the source frequency is w0 + dw)
    uPmax = min(0, kppmax*(Pmax - Pm) + xPmax),   d(xPmax)/dt = kipmax*(Pmax - Pm),   xPmax held at or below 0
    uPmin = max(0, kppmax*(Pmin - Pm) + xPmin),   d(xPmin)/dt = kipmax*(Pmin - Pm),   xPmin held at or above 0
Q-V droop, with a limiter that keeps Q between Qmin and Qmax:
    Vcmd = Vref + mq*(Qref - Qm) + uQmax + uQmin
    uQmax = min(0, kpqmax*(Qmax - Qm) + xQmax),   d(xQmax)/dt = kiqmax*(Qmax - Qm),   xQmax held at or below 0
    uQmin = max(0, kpqmax*(Qmin - Qm) + xQmin),   d(xQmin)/dt = kiqmax*(Qmin - Qm),   xQmin held at or above 0
  VFlag = 1 (regulates the terminal voltage through a PI loop):
    d(xv)/dt = kiv*(Vcmd - Vm), xv held in [Emin, Emax];   E = clip(kpv*(Vcmd - Vm) + xv, Emin, Emax)
  VFlag = 0 (sets the internal voltage directly):
    E = clip(Vcmd, Emin, Emax)
Initialization: Pref takes the dispatch from the power flow. With QVFlag = 1 the plant controller moves Vref and Qref = 0; with QVFlag = 0 it moves Qref, which starts at the initial Q.
With every limit inactive, the steady-state droops are dP/d(omega) = -1/mp (pu power per pu frequency) and, with VFlag = 1, dQ/dV = -1/mq.

    symbol         meaning                                         example          normal range
    XL             coupling reactance                              0.15 pu          0.05 to 0.25 pu
    mq             Q-V droop gain                                  0.05 pu          0 to 0.20 pu
    kpv            voltage loop proportional gain                  0 pu             0 to 0.01 pu
    kiv            voltage loop integral gain                      5.86 pu/s        3 to 15 pu/s
    Emax, Emin     limits of the voltage loop output               1.15, 0 pu       1 to 1.25 pu, 0 pu
    mp             P-f droop gain                                  0.01 pu          0.005 to 0.05 pu
    Pmax, Pmin     active power limits                             0.9, 0 pu        0.1 to 1 pu, 0 (negative for storage)
    kppmax         overload mitigation proportional gain           0.01 pu          0.005 to 0.05 pu
    kipmax         overload mitigation integral gain               0.1 pu/s         0.05 to 0.2 pu/s
    TPf, TQf, TVf  measurement filter time constants               0.01 s           0.01 to 0.1 s
    Qmax, Qmin     reactive power limits                           0.44, -0.44 pu   0.44 to 1 pu, -0.44 to -1 pu
    kpqmax         Q limiter proportional gain                     3 pu (VFlag 1), 0.1 pu (VFlag 0)    1 to 5 pu, 0 to 0.5 pu
    kiqmax         Q limiter integral gain                         20 pu/s (VFlag 1), 10 pu/s (VFlag 0)    3 to 30 pu/s
    ImaxF          transient current limit                         2 pu             1.5 to 3 pu
    VFlag, QVFlag  mode flags                                      1, 1             0 or 1

Virtual synchronous machine model
Measurement filters: Pm, Qm and Vm as above (TPf, TQf, TVf), and the currents in the PLL frame, d(Idm)/dt = (Id - Idm)/TIf and d(Iqm)/dt = (Iq - Iqm)/TIf.
PLL (frozen when V < VPLLfrz: the PI input is set to 0 and deltaPLL stops):
    Vq_pll = V*sin(theta - deltaPLL)
    dwPLL = clip(kpPLL*Vq_pll + xPLL, dwPLLmin, dwPLLmax),   d(xPLL)/dt = kiPLL*Vq_pll, xPLL held in [dwPLLmin, dwPLLmax]
    d(deltaPLL)/dt = w0*dwPLL;   wPLL = 1 + dwPLL
    Id = Ix*cos(deltaPLL) + Iy*sin(deltaPLL),   Iq = -Ix*sin(deltaPLL) + Iy*cos(deltaPLL), where Ix + j*Iy is the injected current. Once the PLL has locked, Id is about P/V and Iq about -Q/V.
Swing equation:
    w = wm (wFlag = 0) or wPLL (wFlag = 1)
    Tp*d(dP)/dt = (wref - w)/mp - dP   (with Tp = 0, dP = (wref - w)/mp; FFlag = 0 sets dP = 0)
    Pcmd = Pref + dP
    2H*d(dwm)/dt = Pcmd - Pm - D1*dwm - yD,   dwm held in [dwmin, dwmax];   wm = 1 + dwm
    yD = D2*dwm - xD,   d(xD)/dt = wD*(D2*dwm - xD)          (the transient damping sD2/(s + wD))
    d(deltaIT)/dt = w0*(dwm - dwPLL),   deltaIT held in [deltaITmin, deltaITmax]
    delta = deltaIT + deltaPLL                               (so, within the limits, d(delta)/dt = w0*dwm)
  wref starts at 1 and Pref at the dispatch.
Voltage control:
    Vcmd = Vref + mq*(Qref - Qm)     (VdrpFlag = 0)     or     Vcmd = Vref + mq*Iqm     (VdrpFlag = 1: mq acts as a virtual impedance)
    d(xv)/dt = kiv*(Vcmd - Vm), xv held in [Emin, Emax];   E = clip(kpv*(Vcmd - Vm) + xv, Emin, Emax)
  QVFlag as in the droop model.
Steady-state current limits:
    P priority (PQFlag = 1): IdmaxSS = kf*ImaxSS,   IqmaxSS = sqrt(ImaxSS^2 - Idm^2) (0 if negative)
    Q priority (PQFlag = 0): IqmaxSS = kf*ImaxSS,   IdmaxSS = sqrt(ImaxSS^2 - Iqm^2) (0 if negative)
    Emin = sqrt((Vm - IqmaxSS*XL)^2 + (Idm*XL)^2),   Emax = sqrt((Vm + IqmaxSS*XL)^2 + (Idm*XL)^2)
    deltaITmax: d/dt = kI*(IdmaxSS - Idm), held in [0, deltamax]
    deltaITmin: d/dt = kI*(-Ke*IdmaxSS - Idm), held in [-deltamax, 0] (ESFlag = 1, storage); deltaITmin = 0 (ESFlag = 0)
    deltamax = asin(XL*ImaxSS)
With every limit inactive, the steady-state droops are dP/d(omega) = -(1/mp + D1) and, with VdrpFlag = 0, dQ/dV = -1/mq.

    symbol                 meaning                                          example
    Re                     coupling resistance (0 to XL/4)                  0 pu
    XL                     coupling reactance (0.04 to 0.4 pu)              0.1 pu
    mq                     Q-V droop gain                                   0.05 pu
    kpv, kiv               voltage loop gains                               0 pu, 5 pu/s
    mp                     P-f droop gain                                   0.02 pu
    dwmax, dwmin           limits of dwm                                    0.05, -0.05 pu
    kpPLL, kiPLL           PLL gains                                        0.265 pu, 2.65 pu/s
    dwPLLmax, dwPLLmin     limits of the PLL output                         0.2, -0.2 pu
    Tp                     power filter time constant in the droop path     0 s
    H                      inertia constant                                 0.5 s
    D1                     damping                                          0 pu
    D2                     transient damping                                100 pu
    wD                     washout corner of the transient damping          50 (listed in pu; as rad/s it is about 8 Hz)
    ImaxSS                 steady-state current limit (at most 1/XL and ImaxF)  1 pu
    kf                     share of ImaxSS given to the priority axis       0.9
    kI                     active current limit integral gain               2 pu/s
    ImaxF                  transient current limit                          1.5 pu
    TPf, TQf, TVf, TIf     measurement filter time constants                0.02 s
    Ke                     scale on the negative active current limit       1
    VPLLfrz                PLL freeze voltage                               0.05 pu
    wFlag, VdrpFlag, QVFlag, PQFlag, FFlag, ESFlag   mode flags             0, 0, 1, 1, 1, 1
