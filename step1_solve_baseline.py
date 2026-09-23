"""
STEP 1 — Solve Coelho et al.'s 17 medium-scale instances with Gurobi (theta = 0,
no degradation) and export the FULL decision-variable assignment, not just the
objective value.

This produces "Coelho's Solution" (Block 1 of the supervisor's diagram) — the
fixed x/y/z/t/delta assignment that Branch A will later re-score under the
degradation-aware objective, without re-optimizing.

Model, constraints, and objective are copied verbatim from
LTPMSP_Gurobi_Degradation_v6.py's build_base_model(), theta forced to 0.

Requires a full (non-size-restricted) Gurobi license to run on the real
17 medium instances — run this on your own licensed machine.

Researcher: Mac-Arthur Numenu Doetein | E-JUST
Baseline: Coelho et al. (2025) DOI: 10.1111/itor.70021
"""

import os
import gurobipy as gp
from gurobipy import GRB

TIME_LIMIT = 600
MIP_GAP = 0.01

SRC_DIR = "./17 Instances Perfect Maintenance/"                                # Coelho's ORIGINAL instance files (7-column job rows)
OUT_DIR = "./Coelhos_Solution_DV_Values/"             # Block 1 output: Coelho's Solution (D.V. values)
os.makedirs(OUT_DIR, exist_ok=True)

INSTANCES = [
    ("LTPMSP_01_00150_00148_00120.txt", 1),
    ("LTPMSP_02_00150_00075_00129.txt", 2),
    ("LTPMSP_03_00150_00102_00091.txt", 3),
    ("LTPMSP_04_00150_00057_00126.txt", 4),
    ("LTPMSP_05_00150_00092_00093.txt", 5),
    ("LTPMSP_06_00150_00071_00101.txt", 6),
    ("LTPMSP_01_00300_00158_00179.txt", 7),
    ("LTPMSP_02_00300_00221_00239.txt", 8),
    ("LTPMSP_03_00300_00112_00177.txt", 9),
    ("LTPMSP_04_00300_00075_00181.txt", 10),
    ("LTPMSP_05_00300_00121_00162.txt", 11),
    ("LTPMSP_06_00300_00119_00176.txt", 12),
    ("LTPMSP_01_00600_00165_00329.txt", 13),
    ("LTPMSP_02_00600_00256_00388.txt", 14),
    ("LTPMSP_03_00600_00120_00288.txt", 15),
    ("LTPMSP_04_00600_00077_00215.txt", 16),
    ("LTPMSP_05_00600_00126_00279.txt", 17),
]


# ── INSTANCE READER (identical to v6) ──────────────────────────────────────

def read_instance(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()

    first = lines[0].strip().split()
    Q, N, M = int(first[0]), int(first[1]), int(first[2])

    jobs, teams = [], []

    i = 1
    while i < len(lines) and len(jobs) < N:
        line = lines[i].strip()
        if line:
            parts = line.split()
            if len(parts) == 7:
                jobs.append({
                    "id": int(parts[0]), "skill": int(parts[1]), "mach": int(parts[2]),
                    "E": float(parts[3]), "L": float(parts[4]),
                    "P": float(parts[5]), "omega": float(parts[6]),
                })
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        if line:
            parts = line.split()
            if len(parts) == 4:
                teams.append({
                    "id": int(parts[0]), "skill": int(parts[1]),
                    "gamma": float(parts[2]), "H": float(parts[3]),
                })
        i += 1

    return Q, N, M, jobs, teams


# ── MODEL BUILDER (identical to v6's build_base_model) ────────────────────

def build_base_model(jobs, teams, N, M, BIG_M):
    compatible = [(i, k) for i in range(N) for k in range(M)
                  if teams[k]["skill"] == jobs[i]["skill"]]
    machine_jobs = {}
    for i, job in enumerate(jobs):
        machine_jobs.setdefault(job["mach"], []).append(i)

    model = gp.Model()
    model.setParam("TimeLimit", TIME_LIMIT)
    model.setParam("OutputFlag", 1)          # verbose so you can see solve progress
    model.setParam("MIPGap", MIP_GAP)

    x = {(i, k): model.addVar(vtype=GRB.BINARY, name=f"x_{i}_{k}") for (i, k) in compatible}
    y = [model.addVar(vtype=GRB.BINARY, name=f"y_{i}") for i in range(N)]
    z = [model.addVar(vtype=GRB.BINARY, name=f"z_{k}") for k in range(M)]
    t = [model.addVar(lb=0, ub=BIG_M, name=f"t_{i}") for i in range(N)]
    delta = {}
    for mach, job_list in machine_jobs.items():
        for a in range(len(job_list)):
            for b in range(a + 1, len(job_list)):
                i1, i2 = job_list[a], job_list[b]
                delta[i1, i2] = model.addVar(vtype=GRB.BINARY, name=f"d_{i1}_{i2}")
    model.update()

    for i in range(N):
        ks = [k for (ii, k) in compatible if ii == i]
        if ks:
            model.addConstr(y[i] == gp.quicksum(x[i, k] for k in ks))
            model.addConstr(gp.quicksum(x[i, k] for k in ks) <= 1)
        else:
            model.addConstr(y[i] == 0)
    for k in range(M):
        iss = [i for (i, kk) in compatible if kk == k]
        if iss:
            model.addConstr(gp.quicksum(jobs[i]["P"] * x[i, k] for i in iss) <= teams[k]["H"])
            model.addConstr(gp.quicksum(x[i, k] for i in iss) <= len(iss) * z[k])
    for i in range(N):
        job = jobs[i]
        model.addConstr(t[i] >= job["E"] * y[i])
        model.addConstr(t[i] + job["P"] * y[i] <= job["L"])
        model.addConstr(t[i] <= BIG_M * y[i])
    for mach, job_list in machine_jobs.items():
        for a in range(len(job_list)):
            for b in range(a + 1, len(job_list)):
                i1, i2 = job_list[a], job_list[b]
                d = delta[i1, i2]
                model.addConstr(
                    t[i1] + jobs[i1]["P"] <=
                    t[i2] + BIG_M * (1 - d) + BIG_M * (1 - y[i1]) + BIG_M * (1 - y[i2]))
                model.addConstr(
                    t[i2] + jobs[i2]["P"] <=
                    t[i1] + BIG_M * d + BIG_M * (1 - y[i1]) + BIG_M * (1 - y[i2]))

    base_obj = (gp.quicksum(z[k] for k in range(M)) +
                gp.quicksum(jobs[i]["omega"] * (1 - y[i]) for i in range(N)))
    return model, base_obj, x, y, z, t, delta, compatible


# ── SOLVE + EXPORT ──────────────────────────────────────────────────────────

def solve_and_export(filename, inst_id):
    Q, N, M, jobs, teams = read_instance(os.path.join(SRC_DIR, filename))
    BIG_M = max(job["L"] for job in jobs)

    model, base_obj, x, y, z, t, delta, compatible = build_base_model(jobs, teams, N, M, BIG_M)
    model.setObjective(base_obj, GRB.MINIMIZE)
    model.optimize()

    if not (model.status in [GRB.OPTIMAL, GRB.TIME_LIMIT] and model.SolCount > 0):
        print(f"Instance {inst_id}: NO SOLUTION FOUND (status={model.status})")
        return

    out_path = os.path.join(OUT_DIR, filename.replace(".txt", "_Coelhos_Solution_DV.txt"))
    with open(out_path, "w") as f:
        f.write(f"# COELHO'S SOLUTION (D.V. VALUES) — theta=0, no degradation\n")
        f.write(f"# Instance {inst_id} — {filename}\n")
        f.write(f"# Objective value: {model.ObjVal:.4f}   Gap: {model.MIPGap*100:.4f}%   "
                f"Status: {'OPTIMAL' if model.status == GRB.OPTIMAL else 'TIME_LIMIT'}\n")
        f.write(f"# Runtime: {model.Runtime:.2f} s\n")
        f.write(f"# Q={Q} N={N} M={M} BIG_M={BIG_M}\n")
        f.write("#\n")

        # y[i]: 1 = job i scheduled internally, 0 = outsourced
        f.write("# --- y[i]: job internally-scheduled indicator ---\n")
        for i in range(N):
            f.write(f"y {i} {int(round(y[i].X))}\n")

        # x[i,k]: job i assigned to crew k (only compatible pairs exist)
        f.write("# --- x[i,k]: job-to-crew assignment (only pairs with x=1 listed) ---\n")
        for (i, k) in compatible:
            if x[i, k].X > 0.5:
                f.write(f"x {i} {k} 1\n")

        # z[k]: crew k activated
        f.write("# --- z[k]: crew activation indicator ---\n")
        for k in range(M):
            f.write(f"z {k} {int(round(z[k].X))}\n")

        # t[i]: scheduled start time of job i (meaningful only if y[i]=1)
        f.write("# --- t[i]: scheduled start time ---\n")
        for i in range(N):
            f.write(f"t {i} {t[i].X:.4f}\n")

        # delta[i1,i2]: relative ordering on shared machines (only for pairs that exist)
        f.write("# --- delta[i1,i2]: machine ordering (only pairs with a value listed) ---\n")
        for (i1, i2), var in delta.items():
            f.write(f"d {i1} {i2} {int(round(var.X))}\n")

    print(f"Instance {inst_id} ({filename}): obj={model.ObjVal:.2f}  "
          f"gap={model.MIPGap*100:.2f}%  -> {out_path}")


def main():
    for filename, inst_id in INSTANCES:
        solve_and_export(filename, inst_id)


if __name__ == "__main__":
    main()
