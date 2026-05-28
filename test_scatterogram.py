"""
Quick test: generate a synthetic far-field E2 array and verify that
_spectrum_to_srgb produces the expected visible colours without
needing a live Lumerical session.
"""

import numpy as np
import matplotlib.pyplot as plt
import colour

# ── replicate _spectrum_to_srgb exactly as in simulation_setup.py ──────────

def spectrum_to_srgb(wavelengths, spd, step=1):
    target_wl = np.arange(380, 781, step)
    sd = colour.SpectralDistribution(np.interp(target_wl, wavelengths, spd), target_wl)
    XYZ = colour.sd_to_XYZ(
        sd,
        cmfs=colour.MSDS_CMFS["CIE 1931 2 Degree Standard Observer"],
        illuminant=colour.SDS_ILLUMINANTS["D65"],
    )
    return np.clip(colour.XYZ_to_sRGB(XYZ / 100.0), 0.0, 1.0)


# ── synthetic wavelength grid (mimics 100 FDTD frequency points) ────────────

wavelengths_nm = np.linspace(380, 800, 100)
n_theta, n_phi = 60, 60

# ── build a synthetic E2 array where:
#    - rows (theta) sweep from 380 nm peak (blue, top) to 700 nm peak (red, bottom)
#    - cols (phi) control the bandwidth (narrow = saturated, wide = white) ──────

scatterogram = np.zeros((n_theta, n_phi, 3))

for i in range(n_theta):
    peak_wl = 400 + (i / (n_theta - 1)) * 320   # 400 nm → 720 nm
    for j in range(n_phi):
        sigma = 10 + (j / (n_phi - 1)) * 120     # narrow → broad bandwidth
        spd = np.exp(-0.5 * ((wavelengths_nm - peak_wl) / sigma) ** 2)
        spd /= spd.max() or 1.0
        scatterogram[i, j] = spectrum_to_srgb(wavelengths_nm, spd)

# ── plot ──────────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(7, 6))
ax.imshow(scatterogram, origin="upper",
          extent=[0, n_phi, n_theta, 0], aspect="auto")
ax.set_xlabel("φ index  →  narrow bandwidth (saturated) to broad (white)")
ax.set_ylabel("θ index  →  400 nm (blue) to 720 nm (red)")
ax.set_title("Synthetic far-field scatterogram\n(spectrum_to_srgb validation)")
plt.tight_layout()
plt.savefig("results/reflectance_plots/test_scatterogram.png", dpi=150)
plt.show()
print("[OK] Test finished. Check results/reflectance_plots/test_scatterogram.png")
