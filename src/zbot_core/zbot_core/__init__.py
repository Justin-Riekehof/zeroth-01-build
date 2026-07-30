"""zbot_core — shared core for the Zeroth-01 build.

One library, two runners (see docs/robot-context.md):
- the local servo GUI on Windows (serial port ``COMx``)
- the Raspberry Pi intent service on Linux (``/dev/ttyUSB*`` / ``/dev/ttyACM*``,
  preferably a stable ``/dev/serial/by-id/...`` path)

Modules:
- ``zbot_core.bus``    — Feetech STS serial bus layer + simulation mock
- ``zbot_core.config`` — repo-config I/O (IDs, limits, offsets, demos)
- ``zbot_core.motion`` — motion/demo execution engine with safety semantics
"""
