"""
STEP 3 (v3, per-job draws) — Solve Coelho et al.'s 17 ORIGINAL instances
(7-column job rows) directly with OUR degradation-aware objective.

CHANGE FROM the previous step3: the repair effectiveness is per job and per
scenario, rho_{i,s} ~ Triangular(0.30, 0.50, 0.70). The draws are regenerated
at runtime with the exact seed scheme used by generate_deg_instances_v3.py
(one fresh random stream per instance, seed = 42, consumed in job row order,
30 draws per job), so Step 3 runs under the IDENTICAL stochastic input as
Step 2 v3. mean_V[i] is computed at runtime with each intervention restoring
the machine by the performing job's own draw:

    V(i,n,s) = (1 - rho_{j(n),s}) * ( V(i,n-1,s) + Lambda*(t_n - t_{n-1}) )
    Vbar_i   = (1/S) * (1/N) * sum_s sum_n V(i,n,s)

Because the job data, draws, and model are identical to Step 2 v3, matching
objective values between the two steps validate that the degradation-aware
instance files faithfully encode the stochastic degradation input.

Requires a full (non-size-restricted) Gurobi license.
Researcher: Mac-Arthur Numenu Doetein | E-JUST
Baseline: Coelho et al. (2025) DOI: 10.1111/itor.70021
"""

import os
import random
import gurobipy as gp
from gurobipy import GRB

TIME_LIMIT = 600
MIP_GAP = 0.01
THETA_BASE = 0.194

# Degradation parameters — identical to generate_deg_instances.py
LAMBDA_RATE = 0.05
RHO_MIN, RHO_MODE, RHO_MAX = 0.30, 0.50, 0.70
N_SCENARIOS = 30
N_PERIODS = 52
RANDOM_SEED = 42

SRC_DIR = "./17 Instances Perfect Maintenance/"                                  # Coelho's ORIGINAL instance files (7-column job rows)
OUT_DIR = "./Step3_Coelhos_Instances_OurObjective_DV_Values_v3/"
os.makedirs(OUT_DIR, exist_ok=True)

# (filename, inst_id, BKV, nodeg_ref) — nodeg_ref used only for theta normalization,
# identical values to Step 1 / Step 2
INSTANCES = [
    ("LTPMSP_01_00150_00148_00120.txt", 1,  1848, 1843),
    ("LTPMSP_02_00150_00075_00129.txt", 2,  30,   24),
    ("LTPMSP_03_00150_00102_00091.txt", 3,  3273, 3273),
    ("LTPMSP_04_00150_00057_00126.txt", 4,  24,   15),
    ("LTPMSP_05_00150_00092_00093.txt", 5,  49,   49),
    ("LTPMSP_06_00150_00071_00101.txt", 6,  106,  104),
    ("LTPMSP_01_00300_00158_00179.txt", 7,  1931, 1925),
    ("LTPMSP_02_00300_00221_00239.txt", 8,  2451, 2445),
    ("LTPMSP_03_00300_00112_00177.txt", 9,  3359, 3359),
    ("LTPMSP_04_00300_00075_00181.txt", 10, 35,   20),
    ("LTPMSP_05_00300_00121_00162.txt", 11, 65,   64),
    ("LTPMSP_06_00300_00119_00176.txt", 12, 308,  304),
    ("LTPMSP_01_00600_00165_00329.txt", 13, 4494, 4480),
    ("LTPMSP_02_00600_00256_00388.txt", 14, 3380, 3340),
    ("LTPMSP_03_00600_00120_00288.txt", 15, 8576, 8567),
    ("LTPMSP_04_00600_00077_00215.txt", 16, 37,   23),
    ("LTPMSP_05_00600_00126_00279.txt", 17, 410,  408),
]


# ── INSTANCE READER (ORIGINAL 7-column job rows — no mean_V) ──────────────

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


# ── VIRTUAL AGE COMPUTATION AT RUNTIME (identical logic to generate_deg_instances.py) ──

def draw_per_job(n_jobs, seed=RANDOM_SEED, s=N_SCENARIOS):
    """Identical seed scheme to generate_deg_instances_v3.py: one fresh
    stream per instance, each job consumes the next s draws in row order."""
    rng = random.Random(seed)
    # Rounded to 6 decimals to match the precision stored in the v3
    # degradation-aware instance files, guaranteeing bitwise-identical
    # draws (and therefore identical Vbar) between Step 2 and Step 3.
    return [[round(rng.triangular(RHO_MIN, RHO_MAX, RHO_MODE), 6) for _ in range(s)]
            for _ in range(n_jobs)]


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


# ── MODEL BUILDER (identical constraints to Step 1 / Step 2) ──────────────

def build_model(jobs, teams, N, M, BIG_M, theta_inst, mean_V):
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


# ── SOLVE + EXPORT ──────────────────────────────────────────────────────────

def solve_and_export(filename, inst_id, bkv, nodeg_ref, z_bar):
    Q, N, M, jobs, teams = read_instance(os.path.join(SRC_DIR, filename))
    BIG_M = max(job["L"] for job in jobs)

    # regenerate the per-job draws with the documented seed scheme, then
    # compute mean_V AT RUNTIME from the original (non-DEG) instance data
    rho = draw_per_job(N)
    mean_V = compute_virtual_ages(jobs, rho, N_SCENARIOS, BIG_M)

    theta_inst = THETA_BASE * (nodeg_ref / z_bar)

    model, base_obj, deg_obj, total_obj, x, y, z, t, delta, compatible = \
        build_model(jobs, teams, N, M, BIG_M, theta_inst, mean_V)
    model.setObjective(total_obj, GRB.MINIMIZE)
    model.optimize()

    if not (model.status in [GRB.OPTIMAL, GRB.TIME_LIMIT] and model.SolCount > 0):
        print(f"Instance {inst_id}: NO SOLUTION FOUND (status={model.status})")
        return

    base_val = base_obj.getValue()
    deg_val = deg_obj.getValue()

    out_path = os.path.join(OUT_DIR, filename.replace(".txt", "_Step3_DV.txt"))
    with open(out_path, "w") as f:
        f.write(f"# STEP 3 (v3) — Coelho's ORIGINAL instance solved with OUR objective\n")
        f.write(f"# per-job rho draws regenerated at runtime (seed=42, row order); mean_V computed at solve time\n")
        f.write(f"# Instance {inst_id} — {filename}  theta_inst={theta_inst:.6f}\n")
        f.write(f"# Total objective: {model.ObjVal:.4f}  (base={base_val:.4f} + degradation={deg_val:.4f})\n")
        f.write(f"# Gap: {model.MIPGap*100:.4f}%   Status: {'OPTIMAL' if model.status == GRB.OPTIMAL else 'TIME_LIMIT'}\n")
        f.write(f"# Q={Q} N={N} M={M} BIG_M={BIG_M}\n")
        f.write("#\n")

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

        f.write("# --- mean_V[i]: virtual age computed at runtime (for reference) ---\n")
        for i in range(N):
            f.write(f"v {i} {mean_V[i]:.6f}\n")

    print(f"Instance {inst_id} ({filename}): total_obj={model.ObjVal:.2f}  "
          f"(base={base_val:.2f} + deg={deg_val:.2f})  gap={model.MIPGap*100:.2f}%  -> {out_path}")


def main():
    nodeg_refs = [nd for (_, _, _, nd) in INSTANCES]
    z_bar = sum(nodeg_refs) / len(nodeg_refs)
    print(f"theta_base={THETA_BASE}  Zbar_nodeg={z_bar:.2f}  rho_seed={RANDOM_SEED} (per-job draws)")
    for filename, inst_id, bkv, nodeg_ref in INSTANCES:
        solve_and_export(filename, inst_id, bkv, nodeg_ref, z_bar)


if __name__ == "__main__":
    main()
