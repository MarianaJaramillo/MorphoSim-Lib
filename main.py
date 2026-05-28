import cadquery as cq
import contextlib
import os
import sys
import json
import yaml
from datetime import datetime

from core.geometry import MorphoStructure
from core.plotting import plot_reflectance, plot_scatterogram
from core.simulation_setup import LumericalSimulation

# lumapi is imported lazily inside the simulation phase
# so the geometry module works without Lumerical installed
lumapi = None

def _load_lumapi():
    """Import lumapi at runtime. Requires Lumerical to be installed."""
    global lumapi
    if lumapi is not None:
        return lumapi
    lumerical_path = "C:\\Program Files\\Lumerical\\v241\\API\\Python"
    if lumerical_path not in sys.path:
        sys.path.append(lumerical_path)
    try:
        import lumapi as _lumapi
        lumapi = _lumapi
        return lumapi
    except ImportError:
        print("[ERROR] Could not import lumapi. Please verify that Lumerical is installed.")
        print(f"        Expected path: {lumerical_path}")
        return None


def load_config(config_path):
    """Load simulation configuration from a YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def main():
    # Select configuration file
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

    # Ask the user for the experiment name
    base_name = input(f"Enter experiment name for [{species}] (no extension): ").strip()
    if not base_name:
        print("[ERROR] A valid name is required.")
        return

    # Output directories organized by species
    stl_dir = os.path.join("results", "model", species)
    csv_dir = os.path.join("results", "reflectance_data", species)
    plots_dir = os.path.join("results", "reflectance_plots", species)
    simfile_dir = os.path.join("results", "simulation_file", species)
    logs_dir = os.path.join("results", "logs", species)
    configs_dir = os.path.join("results", "configs", species)
    for d in [stl_dir, csv_dir, plots_dir, simfile_dir, logs_dir, configs_dir]:
        os.makedirs(d, exist_ok=True)

    # --- Save exact configuration for this run ---
    config_record = {
        "base_name": base_name,
        "species": species,
        "config_file": config_file,
        "timestamp": datetime.now().isoformat(),
        "config": config
    }
    config_save_path = os.path.join(configs_dir, f"{base_name}.json")
    with open(config_save_path, "w") as f:
        json.dump(config_record, f, indent=2)
    print(f"[OK] Configuration saved at: {config_save_path}")

    # Ask what type of analysis the user wants
    print("\nWhat type of analysis do you want to run?")
    print("  [1] Reflectance spectrum")
    print("  [2] Scatterogram (far field)")
    analysis_type_choice = input("Select (1 or 2): ").strip()
    if analysis_type_choice not in ("1", "2"):
        print("[ERROR] Invalid choice. Enter 1 or 2.")
        return
    run_reflectance = analysis_type_choice == "1"
    run_scatterogram = analysis_type_choice == "2"

    # Ask about polarization only when computing reflectance
    if run_reflectance:
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
        analysis_mode = "total"  # not used for scatterogram

    print(f"\n--- [PHASE 1] Geometry Generation ---")

    try:
        morpho = MorphoStructure(config)
        model = morpho.build_full_system()


        stl_path = os.path.abspath(os.path.join(stl_dir, f"{base_name}.stl"))
        cq.exporters.export(model, stl_path, tolerance=0.01, angularTolerance=0.5)
        print(f"[OK] STL file saved at: {stl_path}")

        
        # --- [PHASE 1.5] Save Lumerical project and script files ---
        fsp_path = os.path.abspath(os.path.join(simfile_dir, f"{base_name}.fsp"))
        lsf_path = os.path.abspath(os.path.join(simfile_dir, f"{base_name}.lsf"))
        log_path = os.path.abspath(os.path.join(logs_dir, f"{base_name}.log"))
        
        # --- [PHASE 2] Lumerical ---
        print(f"\n--- [PHASE 2] Configuring Simulation ---")

        lumapi = _load_lumapi()
        if lumapi is None:
            return

        fdtd = lumapi.FDTD(hide=False)
        sim = LumericalSimulation(fdtd, config)


        # 1. Define materials (n=1.56)
        sim.setup_materials()
        sim.import_geometry(stl_path)
        sim.setup_fdtd_region()
        sim.add_source(polarization=45) # Inject in Y
        sim.add_monitors()

        # Save the simulation project file (.fsp)
        fdtd.save(fsp_path)
        print(f"[OK] FDTD project saved at: {fsp_path}")

        # Optionally, save the simulation script (.lsf) if available
        try:
            simfile_dir_unix = simfile_dir.replace("\\", "/")
            fdtd.eval(f'cd("{simfile_dir_unix}"); save("{base_name}.lsf");')
            print(f"[OK] Lumerical script saved at: {lsf_path}")
        except Exception as e:
            print(f"[WARN] Could not save .lsf script: {e}")

        
        print("\n[FDTD] Running simulation...")
        # Redirect stdout to log file during simulation run
        with open(log_path, "w") as log_file, contextlib.redirect_stdout(log_file):
            fdtd.run()
        print(f"[OK] Simulation log saved at: {log_path}")

        # --- [PHASE 3] Results ---
        print(f"\n--- [PHASE 3] Analysis and Visualisation ---")

        if run_reflectance:
            res = sim.analyze_results(mode=analysis_mode)
            if res:
                csv_name = f"{base_name}.csv"
                sim.save_results(res, filename=csv_name, folder=csv_dir)
                plot_reflectance(
                    res,
                    title=f"{base_name} – {analysis_mode}",
                    save_path=os.path.join(plots_dir, f"{base_name}_reflectance.png"),
                )

        if run_scatterogram:
            ff = sim.get_far_field(monitor_name="R_monitor")
            plot_scatterogram(
                ff["scatterogram"],
                title=f"{base_name} – far field",
                save_path=os.path.join(plots_dir, f"{base_name}_scatterogram.png"),
            )

        input("\nPress Enter to close the simulation and exit...")
        

    except Exception as e:
        print(f"\n[ERROR]: {e}")
        

if __name__ == "__main__":
    main()