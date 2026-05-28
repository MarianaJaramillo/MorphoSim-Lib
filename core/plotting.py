import os

import matplotlib.pyplot as plt
import numpy as np


def plot_reflectance(results, title="Reflectance Spectrum", save_path=None):
    """
    Plot wavelength vs reflectance from analyze_results output.

    Args:
        results (dict): Output from LumericalSimulation.analyze_results().
        title (str): Plot title.
        save_path (str): Optional path to save the figure.
    """
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(results["lambda"], results["R"], label="R")
    if "R_total" in results:
        ax.plot(results["lambda"], results["R_total"], label="R total", linestyle="--")
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Reflectance")
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend()
    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[OK] Reflectance plot saved at: {save_path}")
    plt.show()
    plt.close(fig)


def plot_scatterogram(scatterogram, title="Far-field Scatterogram", save_path=None):
    """
    Display the far-field colour scatterogram.

    Args:
        scatterogram (np.ndarray): Shape (N_theta, N_phi, 3), sRGB values in [0, 1].
        title (str): Plot title.
        save_path (str): Optional path to save the figure.
    """
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(scatterogram)
    ax.axis("off")
    ax.set_title(title)
    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[OK] Scatterogram saved at: {save_path}")
    plt.show()
    plt.close(fig)
