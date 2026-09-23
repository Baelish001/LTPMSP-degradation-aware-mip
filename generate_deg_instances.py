"""
generate_deg_instances_v3.py

Builds the degradation-aware (imperfect maintenance) instance files from
Coelho et al.'s (2025) 17 medium-scale LTPMSP instances.

DESIGN (v3, per-job draws): every job i receives its OWN 30 repair-
effectiveness draws rho_{i,s} ~ Triangular(0.30, 0.50, 0.70), s = 1..30.
Each job row carries its own 30 draws followed by their average as the
final column (row format: 7 original columns + 30 draws + average = 38
columns), so the full stochastic input is visible in the instance table
itself and every instance is self-contained and fully reproducible.

Seeding: one fresh random stream per instance, seed = 42, consumed in job
row order (job 1 takes draws 1-30 of the stream, job 2 takes draws 31-60,
and so on). Python's random.triangular signature is (low, high, mode).

The mean virtual age Vbar_i is NOT stored. It is recomputed at solve time by
step2_our_solution_export_v3.py from the per-job draws, using the governing
equations of the paper with job-and-scenario-indexed repair effectiveness:

    V(i,n,s) = (1 - rho_{j(n),s}) * ( V(i,n-1,s) + Lambda*(t_n - t_{n-1}) )
    Vbar_i   = (1/S) * (1/N) * sum_s sum_n V(i,n,s)

where j(n) is the job performing the n-th intervention on the machine.
Reference schedule: Inverted-JPA. Sampling window: [0, max_i L_i], N = 52
equal periods.

Researcher: Mac-Arthur Numenu Doetein | E-JUST
Baseline: Coelho et al. (2025) DOI: 10.1111/itor.70021
"""

import os
import random

RHO_MIN, RHO_MODE, RHO_MAX = 0.30, 0.50, 0.70
N_SCENARIOS = 30
RANDOM_SEED = 42

SRC_DIR = "./data/"
OUT_DIR = "./17 Instances Imperfect Maintenance v3/"

INSTANCE_FILES = [
    "LTPMSP_01_00150_00148_00120.txt", "LTPMSP_02_00150_00075_00129.txt",
    "LTPMSP_03_00150_00102_00091.txt", "LTPMSP_04_00150_00057_00126.txt",
    "LTPMSP_05_00150_00092_00093.txt", "LTPMSP_06_00150_00071_00101.txt",
    "LTPMSP_01_00300_00158_00179.txt", "LTPMSP_02_00300_00221_00239.txt",
    "LTPMSP_03_00300_00112_00177.txt", "LTPMSP_04_00300_00075_00181.txt",
    "LTPMSP_05_00300_00121_00162.txt", "LTPMSP_06_00300_00119_00176.txt",
    "LTPMSP_01_00600_00165_00329.txt", "LTPMSP_02_00600_00256_00388.txt",
    "LTPMSP_03_00600_00120_00288.txt", "LTPMSP_04_00600_00077_00215.txt",
    "LTPMSP_05_00600_00126_00279.txt",
]


def read_original_instance(filepath):
    with open(filepath) as f:
        lines = f.readlines()
    first = lines[0].strip().split()
    Q, N, M = int(first[0]), int(first[1]), int(first[2])
    job_lines, team_lines = [], []
    i = 1
    while i < len(lines) and len(job_lines) < N:
        line = lines[i].strip()
        if line:
            parts = line.split()
            if len(parts) == 7:
                job_lines.append(parts)
        i += 1
    while i < len(lines):
        line = lines[i].strip()
        if line:
            team_lines.append(line)
        i += 1
    return Q, N, M, job_lines, team_lines


def draw_per_job(n_jobs, seed=RANDOM_SEED, s=N_SCENARIOS):
    """One fresh stream per instance; each job consumes the next s draws."""
    rng = random.Random(seed)
    draws = []
    for _ in range(n_jobs):
        draws.append([rng.triangular(RHO_MIN, RHO_MAX, RHO_MODE) for _ in range(s)])
    return draws


def write_deg_instance(out_path, Q, N, M, job_lines, team_lines, job_draws):
    with open(out_path, "w") as f:
        f.write(f"{Q} {N} {M}\n")
        f.write("# Job row format: id skill mach E L P omega | 30 rho draws | rho average\n")
        f.write(f"# rho ~ Triangular({RHO_MIN}, {RHO_MODE}, {RHO_MAX}) [low, mode, high] | "
                f"seed = {RANDOM_SEED} per instance, stream consumed in job row order | "
                f"S = {N_SCENARIOS} draws per job\n")
        f.write("# The final column of each job row is that job's average of its 30 draws.\n")
        for parts, draws in zip(job_lines, job_draws):
            avg = sum(draws) / len(draws)
            draw_str = " ".join(f"{d:.6f}" for d in draws)
            f.write(" ".join(parts) + f" {draw_str} {avg:.6f}\n")
        for line in team_lines:
            f.write(line + "\n")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn in INSTANCE_FILES:
        Q, N, M, job_lines, team_lines = read_original_instance(os.path.join(SRC_DIR, fn))
        job_draws = draw_per_job(N)
        out_path = os.path.join(OUT_DIR, fn.replace(".txt", "_DEG.txt"))
        write_deg_instance(out_path, Q, N, M, job_lines, team_lines, job_draws)
        avgs = [sum(d)/len(d) for d in job_draws]
        print(f"  {fn}: N={N}, row averages span [{min(avgs):.4f}, {max(avgs):.4f}]")


if __name__ == "__main__":
    main()
