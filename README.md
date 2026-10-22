# MorphoSim-Lib

A Python library for parametric 3D geometry generation and FDTD optical simulation of *Morpho* butterfly wing nanostructures. Built for research into structural coloration using [CadQuery](https://cadquery.readthedocs.io/) and [Lumerical FDTD](https://www.ansys.com/products/photonics/fdtd).

---

## Authors

This project was created by:
- **Mariana Jaramillo** (mariana.jaramillo2@udea.edu.co)

## Acknowledgments

The author thanks **Juan Pablo Sanchez** for his contribution to the development of this library.

---

## Overview

*Morpho* butterflies produce their vivid iridescent blue through photonic nanostructures on their wing scales — not pigments. This library lets you:

- **Parametrically build** 3D models of ridge-and-branch nanostructures (regular or triangular tree shape, aligned or staggered branches, inclined ridges)
- **Export geometry** as STL for inspection or import into simulation tools
- **Configure and run** Lumerical FDTD simulations via Python API (`lumapi`)
- **Analyze results** as total, crossed-polarizer, or parallel-polarizer reflectance spectra
- **Track every run** with an auto-saved JSON config alongside each output file

The geometry and simulation engine are species-agnostic: any nanostructure
described by the YAML schema below can be built and simulated. This public
repository ships the full configuration for ***Morpho menelaus***, the species
featured in the associated publication, as a working reference. Configuration
files for other species studied in the broader research project are kept
private pending their own publication and are excluded via `.gitignore`.

---

## Project Structure

```
MorphoSim-Lib/
├── config/                  # YAML configuration files (one per species/variant)
│   ├── menelaus_cover.yaml  # public — Morpho menelaus (cover scale)
│   └── menelaus_ground.yaml # public — Morpho menelaus (ground scale)
├── core/
│   ├── __init__.py          # Package exports
│   ├── geometry.py          # Parametric 3D geometry (CadQuery)
│   ├── plotting.py          # Matplotlib plotting helpers
│   └── simulation_setup.py  # Lumerical FDTD setup, analysis, and export
├── notebooks/               # Jupyter notebooks for parameter sweeps and plotting (local only, excluded from git)
├── results/                 # Generated outputs (excluded from git)
│   └── {species}/
│       └── {run_name}/      # ALL files for one run live here
│           ├── run_name.json          # config snapshot
│           ├── run_name.stl           # exported geometry
│           ├── run_name_total.csv     # reflectance / far-field data
│           ├── run_name_reflectance_total.png
│           ├── run_name_reflectance.fsp   # Lumerical project file
│           └── run_name_reflectance.log
├── main.py                  # Entry point
├── LICENSE                  # CC BY 4.0
└── requirements.txt
```

All files produced by a single run are co-located in `results/{species}/{run_name}/`.
This makes it easy to share (`zip results/menelaus/my_run`), delete, or inspect a run
without hunting across multiple type-organised sub-folders.

> **Note on scope:** configuration files and notebooks for species other than
> *Morpho menelaus* are part of ongoing unpublished research and are not
> distributed in this repository (see `.gitignore`).

---

## Requirements

### Python dependencies

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `cadquery` | Parametric 3D geometry |
| `numpy` | Numerical operations |
| `pandas` | CSV result handling |
| `pyyaml` | Configuration file loading |
| `matplotlib` | Reflectance spectrum plotting |
| `colour-science` | CIE XYZ → sRGB conversion for far-field colour maps |

### Lumerical FDTD (optional)

The geometry generation phase works without Lumerical. FDTD simulation (Phase 2 in `main.py`) requires:

- [Ansys Lumerical FDTD](https://www.ansys.com/products/photonics/fdtd) with a valid license
- Default API path: `C:\Program Files\Lumerical\v241\API\Python`
- Override the path without editing code: `set LUMERICAL_API_PATH=C:\your\path` before running.

If Lumerical is not installed, the program runs Phase 1 (geometry + STL export) without errors.

---

## Usage

```bash
python main.py
```

You will be prompted to:

1. **Select a configuration file** from `config/` (listed automatically)
2. **Name the experiment** — all output files use this name, organized under the species folder

Example session:

```
Available configurations:
  [0] menelaus_cover.yaml
  [1] menelaus_ground.yaml

Select configuration (number or name): 1
[OK] Configuration loaded from: config/menelaus_ground.yaml

Enter experiment name for [menelaus] (no extension): G_cross_test
[OK] Run directory : results/menelaus/G_cross_test
[OK] Configuration saved at: results/menelaus/G_cross_test/G_cross_test.json

--- [PHASE 1] Geometry Generation ---
[OK] STL file saved at: results/menelaus/G_cross_test/G_cross_test.stl
```

---

## Configuration Files

Each YAML file in `config/` defines the full nanostructure geometry. The filename convention is `{species}_{variant}.yaml`. The species prefix determines the output subfolder automatically.

Key parameters:

| Parameter | Description | Unit |
|---|---|---|
| `number_of_layers` | Number of chitin/air bilayers per ridge | — |
| `chitin_layer_thickness` | Thickness of each chitin layer | µm |
| `air_layer_thickness` | Thickness of each air gap layer | µm |
| `ridge_trunk_width` | Width of the central trunk | µm |
| `ridge_total_width` | Total width of one ridge (trunk + branches) | µm |
| `number_of_ridges_along_x` | Number of ridges in the X direction | — |
| `air_gap_between_ridges_along_x` | Gap between ridges | µm |
| `branch_arrangement` | `aligned` or `staggered` | — |
| `tree_shape` | `regular` (uniform branches) or `triangular` (tapered) | — |
| `inclination_angle_radians` | Ridge tilt angle | rad |
| `substrate_thickness_along_z` | Thickness of the chitin base substrate | µm |
| `chitin_refractive_index` | Refractive index of chitin | — |

---

## Reproducibility

Every time `main.py` runs, a JSON file is saved at `results/{species}/{experiment_name}/{experiment_name}.json` containing the full config, the source YAML filename, and a timestamp. This makes every result traceable back to its exact parameters.

---

## License

This project is licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE).
You are free to share and adapt this material for any purpose, provided appropriate
credit is given to the authors.
