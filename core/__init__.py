"""MorphoSim-Lib core package.

Public API
----------
MorphoStructure      — assembles the full 3D nanostructure geometry.
LumericalSimulation  — configures, runs, and analyses Lumerical FDTD simulations.
plot_reflectance     — plots a reflectance spectrum from LumericalSimulation results.
plot_far_field       — plots the far-field |E|² map at a single wavelength.
plot_far_field_colored — plots the colour-mapped diffraction scatterogram.
plot_scatterogram    — displays a raw (θ, φ) scatterogram array.
"""

from .geometry import MorphoStructure
from .simulation_setup import LumericalSimulation
from .plotting import (
    plot_reflectance,
    plot_far_field,
    plot_far_field_colored,
    plot_scatterogram,
)

__all__ = [
    "MorphoStructure",
    "LumericalSimulation",
    "plot_reflectance",
    "plot_far_field",
    "plot_far_field_colored",
    "plot_scatterogram",
]
