# LTPMSP Degradation-Aware MIP — Code and Data Repository

Code, benchmark instances, and full solver output backing the paper:

**"Long-Term Preventive Maintenance Scheduling under Imperfect Maintenance with
Stochastic Repair Effectiveness: A Mixed-Integer Programming Approach"**
Mac-Arthur Numenu Doetein, Zakaria Yahia, Islam Ali — ICIEA-EU 2027, Porto, Portugal.

Extends the LTPMSP benchmark instances of Coelho et al. (2025), DOI:
[10.1111/itor.70021](https://doi.org/10.1111/itor.70021), with a stochastic
virtual-age degradation model, solved exactly with Gurobi 13.0.2.

---

## A note on naming, before anything else

Earlier drafts of this project's working files used the label **"Coelho's
Solution"** for two genuinely different things, and it caused real confusion
during review. This repository uses disambiguated names throughout:

| What it actually is | Folder / script name here |
|---|---|
| Our own Gurobi solver's optimal solve of Coelho et al.'s original instance data, under perfect maintenance (θ = 0) | `results/coelho_baseline_solve_dv/` |
| Coelho et al.'s own *published* heuristic result (their ILS/SIM-ILS algorithm's actual output) | **Not reproduced here** — see their paper directly; used in this repo only as the fixed number reported in the paper's Table 2 "Heuristic" column |
| Our full degradation-aware solve (θ = θ_inst) | `results/degradation_aware_solve_dv/` |
| Coelho et al.'s original instance data, re-solved directly under our degradation-aware objective (a revalidation check, not a new result) | `results/step3_revalidation_dv/` |

If you're trying to reproduce the paper's **RPD (%)** column (Table 2), you
need `coelho_baseline_solve_dv/` (ours) against the BKV values published in
Coelho et al. (2025)'s own Table 10 — not against anything else in this repo.

---

## Directory structure

```
data/
  raw_instances/         Coelho et al.'s original 17 medium-scale instances
                          (7 columns per job: id, skill, machine, E, L, P, omega)
  augmented_instances/   Same 17 instances, each job row extended with its own
                          30 repair-effectiveness draws rho_{i,s} + their average
                          (38 columns per job row). Seed 42, fully reproducible.

src/
  generate_deg_instances.py       Builds augmented_instances/ from raw_instances/
  step1_solve_baseline.py         Solves raw_instances/ under theta=0 (Gurobi)
  step2_solve_degradation_aware.py  Solves augmented_instances/ under theta_inst (Gurobi)
  step3_revalidate.py             Re-solves raw_instances/ directly under the
                                    degradation-aware objective, as a check that
                                    step 2's results are correctly reproducible
                                    from the original (non-augmented) instance data
  sensitivity_analysis.py         Reviewer-requested sensitivity analysis over
                                    theta_base, Lambda, and the Triangular bounds
                                    (paper Section 4.8, Tables 3-5). No Gurobi
                                    required -- pure Python, runs in seconds.

results/
  step1_baseline_summary.xlsx
  step2_degradation_aware_summary.xlsx
  step3_revalidation_summary.xlsx
  coelho_baseline_solve_dv/       Full decision-variable output of step 1, per instance
  degradation_aware_solve_dv/     Full decision-variable output of step 2, per instance
  step3_revalidation_dv/          Full decision-variable output of step 3, per instance
```

---

## Reproducing the paper's results

| Paper artifact | How to reproduce |
|---|---|
| Table 2, "Gurobi (No-Deg)" and "RPD (%)" columns | `python src/step1_solve_baseline.py` |
| Table 2, "Degradation Component" / "Total Cost" / "Cost Impact (%)" columns | `python src/step2_solve_degradation_aware.py` |
| Section 4.6, revalidation that step 2's results are recoverable from the original instance data | `python src/step3_revalidate.py` |
| Section 4.8, Tables 3-5 (sensitivity analysis) | `python src/sensitivity_analysis.py` — no Gurobi license needed; verified to reproduce the paper's exact published 81.06% baseline before reporting the alternative-parameter results |
| `data/augmented_instances/` itself | `python src/generate_deg_instances.py` |

`sensitivity_analysis.py` is the only script that does not require Gurobi —
it reuses the already-solved base (no-degradation) costs from Table 2, since
the degradation penalty term has no `y_i` in it (see paper eq. 2) and is
therefore a schedule-independent constant per instance. This is verified
numerically inside the script itself before any results are reported.

---

## Requirements

```
gurobipy>=11.0      # step1, step2, step3 -- requires a Gurobi license
                     # (academic licenses are free at gurobi.com)
openpyxl>=3.1        # for reading/writing the .xlsx summary files
```

`sensitivity_analysis.py` uses only the Python standard library (`os`, `random`)
and needs no license to run.

---

## Stochastic reproducibility

Every random element in this project uses a single documented seed:
**`random.Random(seed=42)`**, one fresh stream per instance, consumed in job
row order, 30 draws per job. This applies identically in
`generate_deg_instances.py`, `step2_solve_degradation_aware.py`,
`step3_revalidate.py`, and `sensitivity_analysis.py`. Any of these scripts,
re-run from scratch, will produce bit-identical `rho_{i,s}` draws.

---

## Citation

If you use this code or data, please cite:

> Doetein, M.N., Yahia, Z., Ali, I. (2027). Long-Term Preventive Maintenance
> Scheduling under Imperfect Maintenance with Stochastic Repair Effectiveness:
> A Mixed-Integer Programming Approach. *ICIEA-EU 2027*, Porto, Portugal.

and the original benchmark instances:

> Coelho, D.G., Souza, M.J.F., Cota, L.P. (2025). A simheuristic-based
> algorithm for the stochastic long-term maintenance scheduling problem.
> *International Transactions in Operational Research*, 33(1), 268-296.
> https://doi.org/10.1111/itor.70021

---

## Contact

Mac-Arthur Numenu Doetein — Egypt-Japan University of Science and Technology (E-JUST)
