# MorphoSim-Lib

A Python library for parametric 3D geometry generation and FDTD optical simulation of *Morpho* butterfly wing nanostructures. Built for research into structural coloration using [CadQuery](https://cadquery.readthedocs.io/) and [Lumerical FDTD](https://www.ansys.com/products/photonics/fdtd).

---

## Authors

This project was created by:
- **Mariana Jaramillo** (mariana.jaramillo2@udea.edu.co)
- **Juan Pablo Sanchez** (pablo.sanchez2@udea.edu.co)

---

## Overview

*Morpho* butterflies produce their vivid iridescent blue through photonic nanostructures on their wing scales — not pigments. This library lets you:

- **Parametrically build** 3D models of ridge-and-branch nanostructures (regular or triangular tree shape, aligned or staggered branches, inclined ridges)
- **Export geometry** as STL for inspection or import into simulation tools
- **Configure and run** Lumerical FDTD simulations via Python API (`lumapi`)
- **Analyze results** as total, crossed-polarizer, or parallel-polarizer reflectance spectra
- **Track every run** with an auto-saved JSON config alongside each output file

Currently supports models for *Morpho rhetenor* and *Morpho menelaus*.

---

## Project Structure

```
MorphoSim-Lib/
├── config/                  # YAML configuration files (one per species/variant)
│   └── menelaus_ground.yaml
├── core/
│   ├── geometry.py          # Parametric 3D geometry (CadQuery)
│   └── simulation_setup.py  # Lumerical FDTD setup, analysis, and export
├── notebooks/               # Jupyter notebooks for parameter sweeps and plotting
├── results/                 # Generated outputs (excluded from git)
│   ├── configs/             # JSON snapshot of config for each run
│   ├── logs/                # Lumerical simulation logs
│   ├── model/               # Exported STL files
│   ├── reflectance_data/    # CSV reflectance spectra
│   └── simulation_file/     # Lumerical .fsp project files
├── main.py                  # Entry point
└── requirements.txt
```

All output folders are organized by species (e.g., `results/model/menelaus/`).

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

### Lumerical FDTD (optional)

The geometry generation phase works without Lumerical. FDTD simulation (Phase 2 in `main.py`) requires:

- [Ansys Lumerical FDTD](https://www.ansys.com/products/photonics/fdtd) with a valid license
- Default API path: `C:\Program Files\Lumerical\v241\API\Python`

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
  [0] menelaus_ground.yaml
  [1] rhetenor.yaml

Select configuration (number or name): 0
[OK] Configuration loaded from: config/menelaus_ground.yaml

Enter experiment name for [menelaus] (no extension): G_cross_test
[OK] Configuration saved at: results/configs/menelaus/G_cross_test.json

--- [PHASE 1] Geometry Generation ---
[OK] STL file saved at: results/model/menelaus/G_cross_test.stl
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

Every time `main.py` runs, a JSON file is saved at `results/configs/{species}/{experiment_name}.json` containing the full config, the source YAML filename, and a timestamp. This makes every result traceable back to its exact parameters.

---

## License

This project is part of ongoing MSc research. License TBD.
