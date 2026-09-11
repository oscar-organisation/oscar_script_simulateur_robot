"""Print OSCAR ScriptNode code embedded in supermarket.usd without running it."""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "sync_loads": True})

import omni.usd
from isaacsim.core.utils.stage import is_stage_loading, open_stage

try:
    open_stage("/root/Documents/supermarket.usd")
    while is_stage_loading():
        app.update()
    stage = omni.usd.get_context().get_stage()
    for prim in stage.Traverse():
        path = prim.GetPath().pathString.lower()
        if "oscar" not in path and "graph" not in path:
            continue
        print("PRIM", prim.GetPath(), prim.GetTypeName(), flush=True)
        for attribute in prim.GetAttributes():
            name = attribute.GetName().lower()
            if "script" in name or "code" in name:
                print("ATTR", attribute.GetName(), repr(attribute.Get()), flush=True)
finally:
    app.close()
