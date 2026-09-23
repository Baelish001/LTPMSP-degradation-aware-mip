"""
STEP 2 (v3, per-job draws) — Solve the degradation-aware LTPMSP model.

CHANGE FROM v2: every job now has its OWN 30 repair-effectiveness draws
rho_{i,s}, carried directly in its job row. Row format: the 7 original
columns, then the 30 draws, then the average as the final (38th) column.

This script:
  1. Reads the per-job draw matrix rho[i][s] from each instance file and
     validates each job's stated average against its draws.
  2. Recomputes the mean virtual age Vbar_i at solve time. In scenario s,
     the intervention performed by job j restores the machine with that
     job's own draw rho[j][s]:
         V(i,n,s) = (1 - rho_{j(n),s}) * ( V(i,n-1,s) + Lambda*(t_n - t_{n-1}) )
         Vbar_i   = (1/S) * (1/N) * sum_s sum_n V(i,n,s)
     Per-scenario simulation FIRST, averaging SECOND. Reference schedule:
     Inverted-JPA. Sampling window: [0, max_i L_i], N = 52 equal periods.
  3. Builds and solves the degradation-aware MIP with objective
         base_obj + theta_inst * sum_i Vbar_i
     and exports the full DV assignment.

NOTE: because the draws are now job-specific, the Vbar_i values differ from
the earlier scenario-level design. Step 2 and Step 3 results supersede all
previous degradation outputs.

Requires a full (non-size-restricted) Gurobi license.
Researcher: Mac-Arthur Numenu Doetein | E-JUST
Baseline: Coelho et al. (2025) DOI: 10.1111/itor.70021
"""

import os
import gurobipy as gp
from gurobipy import GRB

TIME_LIMIT = 600
MIP_GAP = 0.01
THETA_BASE = 0.194

LAMBDA_RATE = 0.05
N_PERIODS = 52

SRC_DIR = "./17 Instances Imperfect Maintenance v3/"
OUT_DIR = "./Our_Solution_DV_Values_v3/"
os.makedirs(OUT_DIR, exist_ok=True)

INSTANCES = [
    ("LTPMSP_01_00150_00148_00120_DEG.txt", 1,  1848, 1843),
    ("LTPMSP_02_00150_00075_00129_DEG.txt", 2,  30,   24),
    ("LTPMSP_03_00150_00102_00091_DEG.txt", 3,  3273, 3273),
    ("LTPMSP_04_00150_00057_00126_DEG.txt", 4,  24,   15),
    ("LTPMSP_05_00150_00092_00093_DEG.txt", 5,  49,   49),
    ("LTPMSP_06_00150_00071_00101_DEG.txt", 6,  106,  104),
    ("LTPMSP_01_00300_00158_00179_DEG.txt", 7,  1931, 1925),
    ("LTPMSP_02_00300_00221_00239_DEG.txt", 8,  2451, 2445),
    ("LTPMSP_03_00300_00112_00177_DEG.txt", 9,  3359, 3359),
    ("LTPMSP_04_00300_00075_00181_DEG.txt", 10, 35,   20),
    ("LTPMSP_05_00300_00121_00162_DEG.txt", 11, 65,   64),
    ("LTPMSP_06_00300_00119_00176_DEG.txt", 12, 308,  304),
    ("LTPMSP_01_00600_00165_00329_DEG.txt", 13, 4494, 4480),
    ("LTPMSP_02_00600_00256_00388_DEG.txt", 14, 3380, 3340),
    ("LTPMSP_03_00600_00120_00288_DEG.txt", 15, 8576, 8567),
    ("LTPMSP_04_00600_00077_00215_DEG.txt", 16, 37,   23),
    ("LTPMSP_05_00600_00126_00279_DEG.txt", 17, 410,  408),
]


def read_instance_v3(filepath):
    """Job row format: id skill mach E L P omega | 30 rho draws | rho average
    (38 whitespace-separated columns). Comment lines start with #."""
    with open(filepath) as f:
        lines = f.readlines()

    first = lines[0].strip().split()
    Q, N, M = int(first[0]), int(first[1]), int(first[2])

    jobs, teams, rho = [], [], []

    i = 1
    while i < len(lines) and len(jobs) < N:
        line = lines[i].strip()
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) == 38:
                draws = [float(v) for v in parts[7:37]]
                stated_avg = float(parts[37])
                if abs(sum(draws) / len(draws) - stated_avg) > 1e-5:
                    raise ValueError(
                        f"rho average mismatch for job {parts[0]} in {filepath}")
                jobs.append({
                    "id": int(parts[0]), "skill": int(parts[1]), "mach": int(parts[2]),
                    "E": float(parts[3]), "L": float(parts[4]),
                    "P": float(parts[5]), "omega": float(parts[6]),
                    "rho_avg": stated_avg,
                })
                rho.append(draws)
            elif len(parts) in (7, 8):
                raise ValueError(
                    f"{filepath}: job row has {len(parts)} columns; expected 38 "
                    f"(7 original + 30 draws + average). Wrong instance file version?")
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) == 4:
                teams.append({
                    "id": int(parts[0]), "skill": int(parts[1]),
                    "gamma": float(parts[2]), "H": float(parts[3]),
                })
        i += 1

    if len(jobs) != N:
        raise ValueError(f"{filepath}: parsed {len(jobs)} jobs, expected {N}")

    S = len(rho[0])
    return Q, N, M, jobs, teams, rho, S


def compute_virtual_ages(jobs, rho, S, horizon):
    """rho[i][s]: draw of job index i in scenario s. In scenario s, the
    intervention of job j restores with rho[j][s]. Per-scenario simulation
    first, averaging second."""
    N = len(jobs)
    week_len = horizon / N_PERIODS
    week_points = [(w + 1) * week_len for w in range(N_PERIODS)]

    machine_jobs = {}
    for i, job in enumerate(jobs):
        machine_jobs.setdefault(job["mach"], []).append(i)

    sum_V = [0.0] * N

    for s in range(S):
        for mach, job_idx_list in machine_jobs.items():
            ordered = sorted(job_idx_list, key=lambda i: jobs[i]["L"])
            events = [(max(jobs[i]["L"] - jobs[i]["P"], 0.0), i) for i in ordered]

            ev_idx = 0
            V_prev = 0.0
            t_prev = 0.0
            current_job = events[0][1] if events else None

            for wp in week_points:
                while ev_idx < len(events) and events[ev_idx][0] <= wp:
                    t_ev, j_ev = events[ev_idx]
                    dt = max(t_ev - t_prev, 0.0)
                    V_prev = (1.0 - rho[j_ev][s]) * (V_prev + LAMBDA_RATE * dt)
                    t_prev = t_ev
                    current_job = j_ev
                    ev_idx += 1

                dt_w = max(wp - t_prev, 0.0)
                V_at_week = V_prev + LAMBDA_RATE * dt_w
                if current_job is not None:
                    sum_V[current_job] += V_at_week

    return [(sum_V[i] / S) / N_PERIODS for i in range(N)]


def build_degradation_model(jobs, teams, N, M, BIG_M, theta_inst, mean_V):
    compatible = [(i, k) for i in range(N) for k in range(M)
                  if teams[k]["skill"] == jobs[i]["skill"]]
    machine_jobs = {}
    for i, job in enumerate(jobs):
        machine_jobs.setdefault(job["mach"], []).append(i)

    model = gp.Model()
    model.setParam("TimeLimit", TIME_LIMIT)
    model.setParam("OutputFlag", 1)
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
    deg_obj = gp.quicksum(theta_inst * mean_V[i] for i in range(N))
    total_obj = base_obj + deg_obj

    return model, base_obj, deg_obj, total_obj, x, y, z, t, delta, compatible


def solve_and_export(filename, inst_id, bkv, nodeg_ref, z_bar):
    Q, N, M, jobs, teams, rho, S = read_instance_v3(os.path.join(SRC_DIR, filename))
    BIG_M = max(job["L"] for job in jobs)

    mean_V = compute_virtual_ages(jobs, rho, S, BIG_M)
    theta_inst = THETA_BASE * (nodeg_ref / z_bar)

    model, base_obj, deg_obj, total_obj, x, y, z, t, delta, compatible = \
        build_degradation_model(jobs, teams, N, M, BIG_M, theta_inst, mean_V)
    model.setObjective(total_obj, GRB.MINIMIZE)
    model.optimize()

    if not (model.status in [GRB.OPTIMAL, GRB.TIME_LIMIT] and model.SolCount > 0):
        print(f"Instance {inst_id}: NO SOLUTION FOUND (status={model.status})")
        return

    base_val = base_obj.getValue()
    deg_val = deg_obj.getValue()

    out_path = os.path.join(OUT_DIR, filename.replace("_DEG.txt", "_Our_Solution_DV.txt"))
    with open(out_path, "w") as f:
        f.write(f"# OUR SOLUTION (D.V. VALUES) — degradation-aware, per-job rho draws\n")
        f.write(f"# Instance {inst_id} — {filename}  theta_inst={theta_inst:.6f}\n")
        f.write(f"# S={S} draws per job read from instance file; Vbar recomputed at solve time\n")
        f.write(f"# Total objective: {model.ObjVal:.4f}  (base={base_val:.4f} + degradation={deg_val:.4f})\n")
        f.write(f"# Gap: {model.MIPGap*100:.4f}%   Status: "
                f"{'OPTIMAL' if model.status == GRB.OPTIMAL else 'TIME_LIMIT'}\n")
        f.write(f"# Q={Q} N={N} M={M} BIG_M={BIG_M}\n#\n")
        f.write("# --- y[i]: job internally-scheduled indicator ---\n")
        for i in range(N):
            f.write(f"y {i} {int(round(y[i].X))}\n")
        f.write("# --- x[i,k]: job-to-crew assignment (only pairs with x=1 listed) ---\n")
        for (i, k) in compatible:
            if x[i, k].X > 0.5:
                f.write(f"x {i} {k} 1\n")
        f.write("# --- z[k]: crew activation indicator ---\n")
        for k in range(M):
            f.write(f"z {k} {int(round(z[k].X))}\n")
        f.write("# --- t[i]: scheduled start time ---\n")
        for i in range(N):
            f.write(f"t {i} {t[i].X:.4f}\n")
        f.write("# --- delta[i1,i2]: machine ordering (only pairs with a value listed) ---\n")
        for (i1, i2), var in delta.items():
            f.write(f"d {i1} {i2} {int(round(var.X))}\n")

    print(f"Instance {inst_id} ({filename}): total_obj={model.ObjVal:.2f}  "
          f"(base={base_val:.2f} + deg={deg_val:.2f})  gap={model.MIPGap*100:.2f}%")


def main():
    nodeg_refs = [nd for (_, _, _, nd) in INSTANCES]
    z_bar = sum(nodeg_refs) / len(nodeg_refs)
    print(f"theta_base={THETA_BASE}  Zbar_nodeg={z_bar:.2f}")
    for filename, inst_id, bkv, nodeg_ref in INSTANCES:
        solve_and_export(filename, inst_id, bkv, nodeg_ref, z_bar)


if __name__ == "__main__":
    main()
