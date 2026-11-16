"""Run one standalone debug bmodel on the board and save all outputs."""
import sys

import numpy as np
import sophon.sail as sail

bmodel, inp, out = sys.argv[1:4]
eng = sail.Engine(bmodel, 0, sail.IOMode.SYSIO)
g = eng.get_graph_names()[0]
print("graph", g, "inputs", eng.get_input_names(g), "outputs", eng.get_output_names(g), flush=True)
data = dict(np.load(inp))
res = eng.process(g, {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in data.items()})
np.savez(out, **{k: np.asarray(v, dtype=np.float32) for k, v in res.items()})
print({k: np.asarray(v).shape for k, v in res.items()}, flush=True)
