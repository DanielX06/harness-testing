WHAT IS KNOWN ABOUT THE DEVICE AND THE GRID (operator documentation)
- The device is an inverter-based unit rated 900 MVA. Its terminal is bus 3, which connects to bus 9 through its step-up transformer (see system_diagram.png).
- Its documentation says it supports grid frequency through active-power droop and regulates voltage through reactive-power droop. Its control structure, gains and time constants are not documented. Identifying its terminal behaviour is the task.
- The operator sets its active-power dispatch and its voltage schedule. runs.json gives both for each recording, and voltage_setpoint_pu logs the setpoint over time.
- The rest of the network is a ten-bus, two-area system with three synchronous generators, each with a governor and an exciter. Loads are constant impedance, so their P and Q scale with V squared. No secondary control restores frequency, so after an event the frequency can settle away from nominal and the bus angle keeps drifting.
