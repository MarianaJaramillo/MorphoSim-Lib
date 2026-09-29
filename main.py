"""MorphoSim-Lib — command-line entry point.

Workflow
--------
Phase 0  — Load a YAML configuration file and name the experiment.
Phase 0.5 — Collect all user choices up front (analysis type, angles, etc.).
Phase 1  — Generate the 3D geometry with CadQuery and export to STL.
Phase 2  — Configure the Lumerical FDTD simulation (materials, region, source, monitors).
Phase 3  — Run the simulation(s), extract results, and save plots / CSV data.
"""

import cadquery as cq
import contextlib
import os
import sys
import json
import yaml
import numpy as np
import pandas as pd
from datetime import datetime

from core.geometry import MorphoStructure
from core.plotting import plot_reflectance, plot_far_field, plot_far_field_colored, plot_scatterogram
from core.simulation_setup import LumericalSimulation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the Lumerical Python API directory.  Override by setting the
# environment variable LUMERICAL_API_PATH before launching the script.
LUMERICAL_API_PATH = os.environ.get(
    "LUMERICAL_API_PATH",
    r"C:\Program Files\Lumerical\v241\API\Python",
)

# Half-angle (aperture) of the virtual angle-resolved detector (degrees).
# Equivalent to the NA of a collection lens; not exposed to the user because
# most users have no basis to choose a value — the default is sensible for
# specular + first-order reflection from these periodic nanostructures.
DETECTION_HALFANGLE_DEG_DEFAULT = 5.0

# lumapi is imported lazily inside the simulation phase so the geometry
# module works on machines where Lumerical is not installed.
lumapi = None


def _load_lumapi():
    """Import lumapi at runtime. Requires Lumerical to be installed."""
    global lumapi
    if lumapi is not None:
        return lumapi
    if LUMERICAL_API_PATH not in sys.path:
        sys.path.append(LUMERICAL_API_PATH)
    try:
        import lumapi as _lumapi
        lumapi = _lumapi
        return lumapi
    except ImportError:
        print("[ERROR] Could not import lumapi. Please verify that Lumerical is installed.")
        print(f"        Expected path: {LUMERICAL_API_PATH}")
        return None


def load_config(config_path):
    """Load simulation configuration from a YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def run_polarization_pass(stl_path, config, simfile_dir, logs_dir, base_name,
                           pol_label, polarization_value,
                           theta_deg=0.0, phi_deg=0.0, use_bfast=False):
    """
    Run ONE complete FDTD pass (materials -> geometry -> region -> source ->
    monitors -> save -> run) for a single source polarization, in its own
    fresh Lumerical session.

    Each pass gets its own .fsp/.lsf/.log files, named with `pol_label`, so
    that running several passes for the same base_name (e.g. one for 'TE' and
    one for 'TM' to build an unpolarized far field) never overwrites another
    pass's files.

    Args:
        stl_path (str): Path to the geometry STL already exported.
        config (dict): Simulation configuration.
        simfile_dir, logs_dir (str): Output directories.
        base_name (str): Experiment name chosen by the user.
        pol_label (str): Short tag used in filenames, e.g. "TE", "TM", "45deg".
        polarization_value: Passed straight to LumericalSimulation.add_source
            (e.g. "TE", "TM", or a numeric angle in degrees).
        theta_deg (float): Polar angle of incidence (illumination), forwarded
            to both setup_fdtd_region (boundary conditions) and add_source
            (source angle) so they stay consistent.
        phi_deg (float): Azimuthal angle of incidence — not yet exposed as a
            user-facing control, kept at 0.
        use_bfast (bool): Fixed-angle broadband injection — see
            LumericalSimulation.add_source's docstring.

    Returns:
        (sim, fsp_path): the LumericalSimulation wrapper, with its Lumerical
        session still OPEN (call sim.fdtd.close() when you're done pulling
        results from it), and the path of the saved .fsp file.
    """
    fsp_path = os.path.abspath(os.path.join(simfile_dir, f"{base_name}_{pol_label}.fsp"))
    lsf_path = os.path.abspath(os.path.join(simfile_dir, f"{base_name}_{pol_label}.lsf"))
    log_path = os.path.abspath(os.path.join(logs_dir, f"{base_name}_{pol_label}.log"))

    fdtd = lumapi.FDTD(hide=False)
    sim = LumericalSimulation(fdtd, config)

    sim.setup_materials()
    sim.import_geometry(stl_path)
    sim.setup_fdtd_region(illumination_theta_deg=theta_deg)
    sim.add_source(polarization=polarization_value, theta_deg=theta_deg,
                    phi_deg=phi_deg, use_bfast=use_bfast)
    sim.add_monitors()

    fdtd.save(fsp_path)
    print(f"[OK] FDTD project saved at: {fsp_path}")

    try:
        simfile_dir_unix = simfile_dir.replace("\\", "/")
        fdtd.eval(f'cd("{simfile_dir_unix}"); save("{base_name}_{pol_label}.lsf");')
        print(f"[OK] Lumerical script saved at: {lsf_path}")
    except Exception as e:
        print(f"[WARN] Could not save .lsf script: {e}")

    print(f"\n[FDTD] Running simulation ({pol_label})...")
    with open(log_path, "w") as log_file, contextlib.redirect_stdout(log_file):
        fdtd.run()
    print(f"[OK] Simulation log saved at: {log_path}")

    return sim, fsp_path


def _close(sim):
    """Best-effort close of a Lumerical session."""
    try:
        sim.fdtd.close()
    except Exception as e:
        print(f"[WARN] Could not close FDTD session cleanly: {e}")


def main():
    # ----------------------------------------------------------------- #
    # [PHASE 0] Configuration + experiment name + output folders         #
    # ----------------------------------------------------------------- #
    config_dir = "config"
    available_configs = [f for f in os.listdir(config_dir) if f.endswith(".yaml")]
    if not available_configs:
        print("[ERROR] No configuration files found in config/")
        return

    print("Available configurations:")
    for i, name in enumerate(available_configs):
        print(f"  [{i}] {name}")
    config_choice = input("Select configuration (number or name): ").strip()
    if config_choice.isdigit():
        config_file = available_configs[int(config_choice)]
    else:
        config_file = config_choice if config_choice.endswith(".yaml") else config_choice + ".yaml"
    config_path = os.path.join(config_dir, config_file)
    if not os.path.exists(config_path):
        print(f"[ERROR] Configuration not found: {config_path}")
        return
    config = load_config(config_path)
    print(f"[OK] Configuration loaded from: {config_path}")

    # Derive species from the config filename
    # Convention: {species}_{variant}.yaml → species is everything before the first '_'
    species = os.path.splitext(config_file)[0].split("_")[0]

    base_name = input(f"Enter experiment name for [{species}] (no extension): ").strip()
    if not base_name:
        print("[ERROR] A valid name is required.")
        return

    # All output files for this run live in a single directory:
    #   results/{species}/{base_name}/
    # This makes it trivial to share, archive, or delete one run without
    # hunting across multiple type-organised sub-folders.
    run_dir = os.path.join("results", species, base_name)
    os.makedirs(run_dir, exist_ok=True)

    # Convenience aliases — point every subsystem at the same run directory.
    stl_dir = run_dir
    csv_dir = run_dir
    plots_dir = run_dir
    simfile_dir = run_dir
    logs_dir = run_dir

    config_record = {
        "base_name": base_name,
        "species": species,
        "config_file": config_file,
        "timestamp": datetime.now().isoformat(),
        "config": config,
    }
    config_save_path = os.path.join(run_dir, f"{base_name}.json")
    with open(config_save_path, "w") as f:
        json.dump(config_record, f, indent=2)
    print(f"[OK] Run directory : {run_dir}")
    print(f"[OK] Configuration saved at: {config_save_path}")

    # ----------------------------------------------------------------- #
    # [PHASE 0.5] Collect ALL run choices up front. We need this before  #
    # touching Lumerical because the far-field options decide whether we #
    # run ONE or TWO FDTD passes.                                        #
    # ----------------------------------------------------------------- #
    print("\nWhat type of analysis do you want to run?")
    print("  [1] Reflectance spectrum")
    print("  [2] Far field – intensity at a single wavelength")
    print("  [3] Far field – colour-mapped diffraction bands (full visible range)")
    analysis_type_choice = input("Select (1, 2 or 3): ").strip()
    if analysis_type_choice not in ("1", "2", "3"):
        print("[ERROR] Invalid choice. Enter 1, 2 or 3.")
        return
    run_reflectance = analysis_type_choice == "1"
    run_scatterogram = analysis_type_choice == "2"
    run_colored_ff = analysis_type_choice == "3"

    analysis_mode = "total"
    illumination_theta_deg = 0.0
    reflectance_detection_mode = "total"   # "total" or "angle"
    detection_theta_deg = 0.0
    detection_phi_deg = 0.0

    if run_reflectance:
        # --- Illumination angle (polar) ---
        theta_input = input(
            "\nPolar illumination angle in degrees (0 = normal incidence): "
        ).strip()
        try:
            illumination_theta_deg = float(theta_input) if theta_input else 0.0
        except ValueError:
            print("[WARN] Invalid angle; defaulting to 0°.")
            illumination_theta_deg = 0.0

        if illumination_theta_deg != 0:
            print(
                "\n[INFO] With oblique incidence and a broadband sweep (380–800 nm), "
                "the injected angle drifts slightly with wavelength relative to the "
                "requested value (known limitation of Bloch BCs in broadband mode)."
            )

        # --- Detection / capture mode ---
        print("\nHow do you want to measure reflectance?")
        print("  [1] Total (hemisphere-integrated, via power monitor)")
        print("  [2] Angle-resolved (virtual detector pointing at a capture angle)")
        detect_choice = input("Select (1 or 2, default 1): ").strip()
        reflectance_detection_mode = "angle" if detect_choice == "2" else "total"

        if reflectance_detection_mode == "total":
            print("\nAre you studying polarization?")
            print("  [1] Yes – crossed polarizers (cross)")
            print("  [2] Yes – parallel polarizers (parallel)")
            print("  [3] No  – total reflectance (total)")
            pol_choice = input("Select (1, 2 or 3): ").strip()
            pol_map = {"1": "cross", "2": "parallel", "3": "total"}
            if pol_choice not in pol_map:
                print("[ERROR] Invalid choice. Enter 1, 2 or 3.")
                return
            analysis_mode = pol_map[pol_choice]
        else:
            det_theta_input = input(
                "\nDetection / capture polar angle in degrees (0 = specular): "
            ).strip()
            try:
                detection_theta_deg = float(det_theta_input) if det_theta_input else 0.0
            except ValueError:
                print("[WARN] Invalid angle; defaulting to 0°.")
                detection_theta_deg = 0.0
            # Aperture/half-angle of the virtual detector is fixed to a
            # sensible default rather than asked — most users have no basis
            # to choose an NA/aperture value.

        # 'cross'/'parallel' need the source at 45 deg to have equal Ex/Ey
        # content to project; 'total' and angle-resolved detection both work
        # fine at 45 deg too, so we keep using the same source polarization
        # angle regardless of detection mode.
        reflectance_polarization = 45

    far_field_mode = None       # "single" or "unpolarized"
    single_pol_angle = 45.0     # used only when far_field_mode == "single"
    target_wl_nm = None         # used only for run_scatterogram
    wl_step = None              # used only for run_colored_ff

    if run_scatterogram or run_colored_ff:
        print("\nIllumination for far field:")
        print("  [1] Polarized (single polarization)")
        print("  [2] Unpolarized (TE + TM incoherent — runs the simulation twice)")
        pol_ff_choice = input("Select (1 or 2, default 1): ").strip()
        if pol_ff_choice == "2":
            far_field_mode = "unpolarized"
        else:
            far_field_mode = "single"
            angle_input = input(
                "Source polarization angle in degrees "
                "(0 = TE, 90 = TM, 45 = default): "
            ).strip()
            try:
                single_pol_angle = float(angle_input) if angle_input else 45.0
            except ValueError:
                print("[WARN] Invalid angle; defaulting to 45°.")
                single_pol_angle = 45.0

    if run_scatterogram:
        wl_input = input(
            "\nEnter the wavelength for the far field (nm, e.g. 450): "
        ).strip()
        try:
            target_wl_nm = float(wl_input)
        except ValueError:
            print("[WARN] Invalid wavelength; defaulting to 450 nm.")
            target_wl_nm = 450.0

    if run_colored_ff:
        step_input = input(
            "\nWavelength step for colour scan (nm, e.g. 10 for fast / 5 for fine): "
        ).strip()
        try:
            wl_step = float(step_input)
            if wl_step < 2:
                print("[WARN] Step too small, clamping to 2 nm.")
                wl_step = 2.0
        except ValueError:
            print("[WARN] Invalid step; using 10 nm.")
            wl_step = 10.0

    # ----------------------------------------------------------------- #
    # [PHASE 1] Geometry Generation (always once — shared by every pass) #
    # ----------------------------------------------------------------- #
    print("\n--- [PHASE 1] Geometry Generation ---")

    try:
        morpho = MorphoStructure(config)
        model = morpho.build_full_system()

        stl_path = os.path.abspath(os.path.join(stl_dir, f"{base_name}.stl"))
        cq.exporters.export(model, stl_path, tolerance=0.01, angularTolerance=0.5)
        print(f"[OK] STL file saved at: {stl_path}")

        # ------------------------------------------------------------- #
        # [PHASE 2] Lumerical                                            #
        # ------------------------------------------------------------- #
        print("\n--- [PHASE 2] Configuring Simulation ---")

        lumapi_mod = _load_lumapi()
        if lumapi_mod is None:
            return

        # ------------------------------------------------------------- #
        # [PHASE 3] Run + Analyze                                        #
        # ------------------------------------------------------------- #
        print("\n--- [PHASE 3] Analysis and Visualisation ---")

        if run_reflectance:
            pass
        if run_reflectance:
            sim, _ = run_polarization_pass(
                stl_path, config, simfile_dir, logs_dir, base_name,
                pol_label="reflectance", polarization_value=reflectance_polarization,
                theta_deg=illumination_theta_deg,
            )
            if reflectance_detection_mode == "total":
                res = sim.analyze_results(mode=analysis_mode)
                tag = analysis_mode
            else:
                res = sim.analyze_results_angle_resolved(
                    r_monitor="R_monitor",
                    detection_theta_deg=detection_theta_deg,
                    detection_phi_deg=detection_phi_deg,
                    detection_halfangle_deg=DETECTION_HALFANGLE_DEG_DEFAULT,
                )
                tag = f"angle{detection_theta_deg:g}"
            if res:
                csv_name = f"{base_name}_{tag}.csv"
                sim.save_results(res, filename=csv_name, folder=csv_dir)
                plot_reflectance(
                    res,
                    title=f"{base_name} – {tag} (theta_inc={illumination_theta_deg:g}deg)",
                    save_path=os.path.join(plots_dir, f"{base_name}_reflectance_{tag}.png"),
                )
            _close(sim)

        if run_scatterogram:
            if far_field_mode == "unpolarized":
                sim_te, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label="TE", polarization_value="TE",
                )
                ff_te = sim_te.get_far_field_at_wavelength(
                    wavelength_nm=target_wl_nm, monitor_name="R_monitor", na=150, nb=150,
                )
                _close(sim_te)

                sim_tm, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label="TM", polarization_value="TM",
                )
                ff_tm = sim_tm.get_far_field_at_wavelength(
                    wavelength_nm=target_wl_nm, monitor_name="R_monitor", na=150, nb=150,
                )
                _close(sim_tm)

                ff = LumericalSimulation.combine_incoherent(ff_te, ff_tm)
                ff_tag = "unpolarized"
            else:
                sim, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label=f"{single_pol_angle:g}deg", polarization_value=single_pol_angle,
                )
                ff = sim.get_far_field_at_wavelength(
                    wavelength_nm=target_wl_nm, monitor_name="R_monitor", na=150, nb=150,
                )
                _close(sim)
                ff_tag = f"{single_pol_angle:g}deg"

            plot_far_field(
                ff,
                title=f"{base_name} – far field ({ff_tag})",
                save_path=os.path.join(
                    plots_dir,
                    f"{base_name}_farfield_{ff_tag}_{int(ff['wavelength_nm'])}nm.png",
                ),
            )
            ux_grid, uy_grid = np.meshgrid(ff["ux"], ff["uy"], indexing='ij')
            ff_df = pd.DataFrame({
                "ux": ux_grid.ravel(),
                "uy": uy_grid.ravel(),
                "E2": ff["E2"].ravel(),
                "theta_deg": ff["theta"].ravel(),
                "phi_deg": ff["phi"].ravel(),
            })
            ff_csv = os.path.join(
                csv_dir,
                f"{base_name}_farfield_{ff_tag}_{int(ff['wavelength_nm'])}nm.csv",
            )
            ff_df.to_csv(ff_csv, index=False)
            print(f"[OK] Far field data saved at: {ff_csv}")

        if run_colored_ff:
            if far_field_mode == "unpolarized":
                sim_te, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label="TE", polarization_value="TE",
                )
                ff_col_te = sim_te.get_far_field_colored(
                    monitor_name="R_monitor", na=150, nb=150,
                    wl_start=380, wl_stop=780, wl_step=wl_step,
                )
                _close(sim_te)

                sim_tm, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label="TM", polarization_value="TM",
                )
                ff_col_tm = sim_tm.get_far_field_colored(
                    monitor_name="R_monitor", na=150, nb=150,
                    wl_start=380, wl_stop=780, wl_step=wl_step,
                )
                _close(sim_tm)

                ff_col = LumericalSimulation.combine_incoherent_colored(ff_col_te, ff_col_tm)
                ff_tag = "unpolarized"
            else:
                sim, _ = run_polarization_pass(
                    stl_path, config, simfile_dir, logs_dir, base_name,
                    pol_label=f"{single_pol_angle:g}deg", polarization_value=single_pol_angle,
                )
                ff_col = sim.get_far_field_colored(
                    monitor_name="R_monitor", na=150, nb=150,
                    wl_start=380, wl_stop=780, wl_step=wl_step,
                )
                _close(sim)
                ff_tag = f"{single_pol_angle:g}deg"

            plot_far_field_colored(
                ff_col,
                title=f"{base_name} – diffraction colour map ({ff_tag})",
                save_path=os.path.join(
                    plots_dir,
                    f"{base_name}_farfield_colored_{ff_tag}.png",
                ),
            )
            ux_g, uy_g = np.meshgrid(ff_col["ux"], ff_col["uy"], indexing='ij')
            total_E2 = ff_col["E2_cube"].sum(axis=2)
            col_df = pd.DataFrame({
                "ux": ux_g.ravel(),
                "uy": uy_g.ravel(),
                "E2_total": total_E2.ravel(),
                "theta_deg": np.degrees(np.arcsin(
                    np.sqrt(np.clip(ux_g**2 + uy_g**2, 0, 1))
                )).ravel(),
                "phi_deg": np.degrees(np.arctan2(uy_g, ux_g)).ravel(),
            })
            col_csv = os.path.join(csv_dir, f"{base_name}_farfield_colored_{ff_tag}.csv")
            col_df.to_csv(col_csv, index=False)
            print(f"[OK] Colour far field data saved at: {col_csv}")

        input("\nPress Enter to exit...")

    except Exception as e:
        print(f"\n[ERROR]: {e}")


if __name__ == "__main__":
    main()