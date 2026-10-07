# Leeds-v1 reference case

This is the first AADTBench reference case: 2024 DfT all-motor-vehicle,
two-way AADT counts matched to the canonical Leeds road network. The generated
CSV files in this directory are frozen inputs to scoring; tool adapters must
not create their own counter-to-link matching.

Regenerate deliberately, after a case-version decision:

```bash
PYTHONPATH=. python benchmark/build_case.py --case cases/leeds-v1
PYTHONPATH=. python benchmark/build_case.py --case cases/leeds-v1 --check
```
