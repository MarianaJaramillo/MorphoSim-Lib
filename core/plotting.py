"""Plotting utilities for MorphoSim-Lib simulation results.

Functions
---------
plot_reflectance        — wavelength vs. reflectance spectrum.
plot_far_field          — direction-cosine (ux, uy) |E|² map at one wavelength.
plot_far_field_colored  — full-hemisphere colour-mapped diffraction scatterogram.
plot_scatterogram       — raw (θ, φ) scatterogram array.
"""

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


def plot_far_field(ff_data, title="Far Field", save_path=None):
    """
    Plot the far-field |E|^2 distribution at a single wavelength as a
    direction-cosine (ux, uy) map projected onto the hemisphere.

    The colour map represents intensity.  The dashed circle marks the
    hemisphere boundary (|u| = 1, i.e. θ = 90°).

    Args:
        ff_data (dict): Output from LumericalSimulation.get_far_field_at_wavelength().
            Required keys: 'E2', 'ux', 'uy', 'wavelength_nm'.
        title (str): Plot title prefix.
        save_path (str): Optional path to save the figure.
    """
    E2 = np.array(ff_data["E2"], dtype=float)
    ux = np.array(ff_data["ux"], dtype=float)
    uy = np.array(ff_data["uy"], dtype=float)
    wl = float(ff_data["wavelength_nm"])
    method = ff_data.get("method", "")

    # Mask region outside the hemisphere (|u| > 1 → evanescent, not physical)
    UX, UY = np.meshgrid(ux, uy, indexing='ij')
    outside = (UX ** 2 + UY ** 2) > 1.0
    E2_masked = E2.copy()
    E2_masked[outside] = np.nan

    fig, ax = plt.subplots(figsize=(6, 5))
    mesh = ax.pcolormesh(ux, uy, E2_masked.T, cmap="hot", shading="auto")

    theta_circle = np.linspace(0, 2 * np.pi, 300)

    # Reference rings at 30°, 60°, 90° (hemisphere boundary)
    for deg, lw, ls, alpha in ((30, 0.5, ":", 0.45), (60, 0.5, ":", 0.45), (90, 0.9, "--", 0.70)):
        r = np.sin(np.radians(deg))
        ax.plot(r * np.cos(theta_circle), r * np.sin(theta_circle),
                color="white", linewidth=lw, linestyle=ls, alpha=alpha)
        ax.text(r + 0.02, 0.02, f"{deg}°", color="white", fontsize=7,
                va="bottom", ha="left", alpha=0.75)

    cbar = plt.colorbar(mesh, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(r"$|E|^2$ (a.u.)")

    ax.set_xlabel(r"$u_x = \sin\theta\cos\phi$")
    ax.set_ylabel(r"$u_y = \sin\theta\sin\phi$")
    method_label = f"  [{method}]" if method else ""
    ax.set_title(f"{title}\n$\\lambda$ = {wl:.1f} nm{method_label}")
    ax.set_aspect("equal")
    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-1.05, 1.05)

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[OK] Far field plot saved at: {save_path}")
    plt.show()
    plt.close(fig)


def plot_far_field_colored(ff_colored, title="Far Field – Diffraction Colour Map",
                          save_path=None):
    """
    Display the colour-mapped far-field scatterogram on the full hemisphere
    (θ ∈ [0°, 90°]).

    Each pixel's colour encodes the perceived hue of the diffracted light at
    that angle; brightness encodes total integrated power.  Diffraction bands
    appear as coloured arcs at their characteristic angles.

    Args:
        ff_colored (dict): Output from LumericalSimulation.get_far_field_colored().
            Required keys: 'rgb', 'ux', 'uy', 'wavelengths'.
        title (str): Plot title.
        save_path (str): Optional path to save the figure.
    """
    rgb = np.array(ff_colored["rgb"], dtype=float)
    ux  = np.array(ff_colored["ux"],  dtype=float)
    uy  = np.array(ff_colored["uy"],  dtype=float)
    wls = ff_colored["wavelengths"]

    # Mask evanescent region (outside hemisphere)
    UX, UY = np.meshgrid(ux, uy, indexing='ij')
    outside = (UX ** 2 + UY ** 2) > 1.0
    rgb_show = rgb.copy()
    rgb_show[outside] = 0.0          # black outside the hemisphere

    fig, ax = plt.subplots(figsize=(6.5, 6))
    # pcolormesh with RGB: pass the transposed array so axes align with ux, uy
    ax.imshow(
        rgb_show.transpose(1, 0, 2),  # (nb, na, 3) → imshow expects (rows, cols, 3)
        origin="lower",
        extent=[ux.min(), ux.max(), uy.min(), uy.max()],
        aspect="equal",
        interpolation="bilinear",
    )

    theta_circle = np.linspace(0, 2 * np.pi, 300)
    # Reference rings
    for deg, lw, ls, alpha in ((30, 0.6, ":", 0.55), (60, 0.6, ":", 0.55), (90, 1.0, "--", 0.80)):
        r = np.sin(np.radians(deg))
        ax.plot(r * np.cos(theta_circle), r * np.sin(theta_circle),
                color="white", linewidth=lw, linestyle=ls, alpha=alpha)
        ax.text(r + 0.02, 0.02, f"{deg}°", color="white", fontsize=7,
                va="bottom", ha="left", alpha=0.80)

    ax.set_xlim(-1.02, 1.02)
    ax.set_ylim(-1.02, 1.02)
    ax.set_xlabel(r"$u_x = \sin\theta\cos\phi$")
    ax.set_ylabel(r"$u_y = \sin\theta\sin\phi$")
    ax.set_title(
        f"{title}\n"
        f"λ = {wls.min():.0f}–{wls.max():.0f} nm  "
        f"({len(wls)} points, Δλ = {(wls[1]-wls[0]) if len(wls)>1 else 0:.0f} nm)"
    )

    plt.tight_layout()
    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[OK] Coloured far field saved at: {save_path}")
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
