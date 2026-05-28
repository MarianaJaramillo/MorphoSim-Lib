import os

import colour
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class LumericalSimulation:
    def __init__(self, fdtd_session, config):
        """
        Initialize a LumericalSimulation object with the given FDTD session and configuration.
        Args:
            fdtd_session: The active Lumerical FDTD session (lumapi.FDTD()).
            config (dict): Configuration dictionary for the simulation and geometry.
        """
        """
        fdtd_session: The active Lumerical instance (lumapi.FDTD()).
        config: The same dictionary we use for geometry.
        """
        self.fdtd = fdtd_session
        self.config = config
        self.period_x = config['ridge_total_width'] + config['air_gap_between_ridges_along_x']
        self.total_width_x = (config['number_of_ridges_along_x'] * config['ridge_total_width'] +
                              (config['number_of_ridges_along_x'] - 1) * config['air_gap_between_ridges_along_x'])
        self.depth_y = config.get('structure_thickness_along_y', 5.0)

    # --- BLOCK 1: MATERIALS ---
    def setup_materials(self):
        """
        Set up the chitin material in the Lumerical session, removing any previous instance and applying the correct parameters.
        """
        """
        Replica of the laboratory logic with format correction for Python.
        """
        import numpy as np # Make sure it's imported
        
        # Parameters
        material_name = "Chitin"
        refractive_index = self.config.get('chitin_refractive_index', 1.56)
        extinction_coefficient = 0
        # Force it to be a numpy array to avoid 'cell array' error
        color_rgb = np.array(([191/255, 0/255], [0/255, 1])) 
        mesh_order = 2
        
        # 1. Preventive cleanup
        if self.fdtd.materialexists(material_name):
            self.fdtd.deletematerial(material_name)

        # 2. Exact logic
        material_handle = self.fdtd.addmaterial("(n,k) Material")
        
        # Use float() and int() to ensure no weird objects are passed
        self.fdtd.setmaterial(material_handle, "Refractive Index", float(refractive_index))
        self.fdtd.setmaterial(material_handle, "Imaginary Refractive Index", float(extinction_coefficient))
        self.fdtd.setmaterial(material_handle, "Mesh Order", int(mesh_order))
        
        # This line was causing problems: we pass the numpy array
        self.fdtd.setmaterial(material_handle, "Color", color_rgb)
        self.fdtd.setmaterial(material_handle, "name", material_name)

        
        print(f"[OK] Material '{material_name}' created successfully.")

    def import_geometry(self, stl_file_path):
        """
        Import the geometry from an STL file into the Lumerical session and assign the chitin material.
        Args:
            stl_file_path (str): Path to the STL file to import.
        """
        """
        Minimalist replica of the laboratory import function.
        """
        # 1. Import with scaling (identical to your colleague)
        # The error probably occurs because we try to move it (set x, y, z) 
        # and the imported STL object doesn't always accept those commands in the same way.
        
        try:
            # First, make sure the file exists (Python check)
            if not os.path.exists(stl_file_path):
                print(f"[ERROR] The file does not exist at the path: {stl_file_path}")
                return

            # Exact command from your colleague
            self.fdtd.stlimport(stl_file_path, 1e-6)
            self.fdtd.set("name", "Morpho_Structure")
            # Material assignment (identical)
            self.fdtd.set("material", "Chitin")
            
            print(f"[OK] Import completed for: {stl_file_path}")
            
        except Exception as e:
            print(f"Specific error in import: {e}")
    # --- BLOCK 2: SCENARIO (FDTD Region and Source) ---

    # --- BLOCK 2: SCENARIO (FDTD Region and Source) ---

    def setup_fdtd_region(self):
        """
        Configure the FDTD simulation region, including boundaries, dimensions, and mesh settings.
        """
        """Configure the FDTD region with Bloch/Periodic logic and Shutoff"""
        fdtd_region = self.fdtd.addfdtd()
        
        # 1. Geometry Parameters
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])
        substrate_height = self.config['substrate_thickness_along_z']
        substrate_gap = self.config['air_gap_below_substrate_along_z']
        
        # 2. Dimensions and Position (Same as your successful manual adjustment)
        fdtd_region.x_span = self.period_x * 1e-6 
        fdtd_region.y_span = (self.depth_y-0.1) * 1e-6
        
        z_min = -(substrate_height + substrate_gap + 0.3)
        #z_max = ridge_height + 0.8
        z_max = ridge_height + 2.5
        fdtd_region.z_span = (z_max - z_min) * 1e-6
        fdtd_region.x, fdtd_region.y = 0, (self.depth_y / 2) * 1e-6
        fdtd_region.z = ((z_max + z_min) / 2) * 1e-6
        
        # 3. Boundary Condition Logic (Suggestion 1 from your colleague)
        # If there is inclination, we use Bloch to handle phase shift
        boundary_condition = "Bloch" if self.config.get('inclination_angle_radians', 0) != 0 else "Periodic"
        
        self.fdtd.set("x min bc", boundary_condition)
        self.fdtd.set("x max bc", boundary_condition)
        self.fdtd.set("y min bc", boundary_condition)
        self.fdtd.set("y max bc", boundary_condition)
        self.fdtd.set("z min bc", "PML")
        self.fdtd.set("z max bc", "PML")
        
        # 4. Resolution and Shutdown (Suggestion 3 from your colleague)
        self.fdtd.setglobalmonitor("frequency points", 100)
        self.fdtd.set("auto shutoff min", 0.001) # Stabilization
        self.fdtd.set("mesh accuracy", 2)

        print(f"[OK] FDTD configured with {boundary_condition} and 100 frequency points.")

    def add_source(self, polarization="TM"):
        """
        Add a parametric source to the simulation, positioned above the ridge tip.
        Args:
            polarization (str): 'TE' or 'TM' polarization for the source.
        """
        """Parametric source placed according to ridge height"""
        source = self.fdtd.addplane()
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])
        
        # Position: 0.2um above the tip
        source_z = ridge_height + 0.3
        
        source.x_span = (self.period_x + 1)* 1e-6
        source.y_span = (self.depth_y + 1)* 1e-6
        source.x, source.y = 0, (self.depth_y / 2) * 1e-6
        source.z = source_z * 1e-6
        
        self.fdtd.set("injection axis", "z-axis")
        self.fdtd.set("direction", "Backward")
        self.fdtd.set("wavelength start", 380e-9)
        self.fdtd.set("wavelength stop", 800e-9)
        #self.fdtd.set("amplitude", 1000000) 
        
        # Polarization
        if polarization == "TE":
            polarization_angle = 0
        elif polarization == "TM":
            polarization_angle = 90
        else:
            try:
                polarization_angle = float(polarization)
            except Exception:
                print(f"[WARNING] Unrecognized polarization value: {polarization}, defaulting to 0 (TE)")
                polarization_angle = 0
        self.fdtd.set("polarization angle", polarization_angle)
        self.fdtd.set("name", f"source_{polarization}")
        self.fdtd.set("amplitude", 1000000) # Standard value (1V/m)
        
        print(f"[OK] {polarization} source injecting at {source_z:.2f}um.")

    # --- BLOCK 3: MONITORS ---

    def add_monitors(self):
        """
        Add reflectance (R) and transmittance (T) monitors to the simulation with fixed names and positions.
        """
        """Adds R and T monitors with fixed names to avoid setnamed errors"""
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])
        substrate_height = self.config['substrate_thickness_along_z']
        substrate_gap = self.config['air_gap_below_substrate_along_z']
        y_position = (self.depth_y / 2) * 1e-6

        # --- R MONITOR ---
        self.fdtd.addpower()
        self.fdtd.set("name", "R_monitor") # <--- The name must go FIRST
        self.fdtd.set("monitor type", "2D Z-normal")
        
        # We use setnamed for dimensions for safety
        self.fdtd.setnamed("R_monitor", "x span", self.period_x * 1e-6)
        self.fdtd.setnamed("R_monitor", "y span", (self.depth_y-0.1) * 1e-6)
        self.fdtd.setnamed("R_monitor", "x", 0)
        self.fdtd.setnamed("R_monitor", "y", y_position)
        self.fdtd.setnamed("R_monitor", "z", (ridge_height + 1.2) * 1e-6)
        
        # Now, we activate the fields
        self.fdtd.setnamed("R_monitor", "output Ex", True)
        self.fdtd.setnamed("R_monitor", "output Ey", True)

        """
        # --- T MONITOR ---
        self.fdtd.addpower()
        self.fdtd.set("name", "T_monitor")
        self.fdtd.set("monitor type", "2D Z-normal")
        self.fdtd.setnamed("T_monitor", "x span", self.period_x * 1e-6)
        self.fdtd.setnamed("T_monitor", "y span", self.depth_y * 1e-6)
        self.fdtd.setnamed("T_monitor", "x", 0)
        self.fdtd.setnamed("T_monitor", "y", y_position)
        self.fdtd.setnamed("T_monitor", "z", -(substrate_height + substrate_gap + 0.2) * 1e-6)
        """
        

        print("[OK] R and T monitors configured correctly.")

    # --- BLOCK 4: DATA ANALYSIS ---

    def analyze_results(self, mode="total", polarization="TM", r_monitor="R_monitor", window_size=15):
        """
        Analyze the simulation results.
        Modes:
            - 'total': Total reflectance (no polarizers)
            - 'cross': Crossed polarizers (projection at -45°)
            - 'parallel': Parallel polarizers (projection at +45°)
        Note: For 'cross' and 'parallel', the source must be set to 45 degrees.
        """
        try:
            # -------------------------------
            # 1. Total reflectance (Power Monitor)
            # -------------------------------
            print(f"[DEBUG] Requesting 'T' result from {r_monitor}...")
            res_potencia = self.fdtd.getresult(r_monitor, "T")
            wavelengths = res_potencia['lambda'].flatten() * 1e9
            r_total_raw = np.abs(res_potencia['T'].flatten())

            def moving_average(data, window):
                if window < 1:
                    return data
                kernel = np.ones(window) / window
                return np.convolve(data, kernel, mode='same')

            # -------------------------------
            # MODE: TOTAL
            # -------------------------------
            if mode == "total":
                r_total_smooth = moving_average(r_total_raw, window_size)
                print("[OK] Total mode processed.")
                return {
                    "lambda": wavelengths,
                    "R": r_total_smooth
                }

            # -------------------------------
            # MODES: CROSS (crossed polarizers) and PARALLEL (parallel polarizers)
            # -------------------------------
            elif mode in ["cross", "parallel"]:
                print(f"[DEBUG] Requesting field dataset 'E' from {r_monitor}...")
                try:
                    e_dataset = self.fdtd.getresult(r_monitor, "E")
                    e_matrix = e_dataset["E"]
                except Exception as e_get:
                    print(f"[CRITICAL ERROR] Could not obtain 'E' field: {e_get}")
                    raise

                # Extract Ex and Ey components
                # Expected shape: [x, y, z, f, component]
                ex_field = e_matrix[:, :, :, :, 0]
                ey_field = e_matrix[:, :, :, :, 1]

                # --- Projection by mode ---
                if mode == "cross":
                    # Projection at -45° (crossed polarizers)
                    e_proj = (ex_field - ey_field) / np.sqrt(2)
                elif mode == "parallel":
                    # Projection at +45° (parallel polarizers)
                    e_proj = (ex_field + ey_field) / np.sqrt(2)

                # Intensity of the projected component
                i_proj = np.sum(np.abs(e_proj) ** 2, axis=(0, 1, 2)).flatten()
                # Total intensity (used to normalize the fraction)
                i_total_fields = np.sum(np.abs(ex_field) ** 2 + np.abs(ey_field) ** 2, axis=(0, 1, 2)).flatten()

                # Fraction of power that survives the analyzer
                fraction_proj = np.divide(
                    i_proj,
                    i_total_fields,
                    out=np.zeros_like(i_proj),
                    where=i_total_fields != 0
                )

                # Apply the fraction to the total reflectance
                r_proj_raw = r_total_raw * fraction_proj
                r_proj_smooth = moving_average(r_proj_raw, window_size)

                print(f"[OK] Reflectance with {'crossed' if mode=='cross' else 'parallel'} polarizer (interference method) calculated.")

                return {
                    "lambda": wavelengths,
                    "R": r_proj_smooth,
                    "R_total": moving_average(r_total_raw, window_size),
                    "polarization_fraction": fraction_proj
                }

        except Exception as e_general:
            print(f"\n[GENERAL FAILURE IN ANALYSIS]: {e_general}")
            import traceback
            traceback.print_exc()
            return None
        
    def save_results(self, results, filename="reflectance_data.csv", folder="results/reflectance_data"):
        """
        Save the wavelength and reflectance data to a CSV file in the results folder.
        Args:
            results (dict): Dictionary with results from analyze_results.
            filename (str): Name of the CSV file to save.
        """
        """
        Saves the wavelength and reflectance data to a CSV file.
        """
        try:
            # 1. Create the DataFrame
            df = pd.DataFrame({
                'wavelength_nm': results['lambda'],
                'reflectance': results['R']
            })
            if 'R_total' in results:
                df['reflectance_total'] = results['R_total']

            # 2. Save in the specified folder
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            df.to_csv(path, index=False)
            print(f"[OK] Data saved successfully at: {path}")
        except Exception as e:
            print(f"[ERROR saving]: {e}")


    def get_far_field(self, monitor_name="R_monitor", n_theta=100, n_phi=100):
        """
        Compute the far-field scatterogram from a Lumerical monitor.

        For each angular point (θ, φ), the full spectral power distribution
        across all simulated wavelengths is converted to a single sRGB colour
        using _spectrum_to_srgb — so the colour reflects the entire visible range.

        Args:
            monitor_name (str): Monitor to query (must have far-field projection enabled).
            n_theta (int): Number of polar angle points for the far-field projection.
            n_phi (int): Number of azimuthal angle points for the far-field projection.

        Returns:
            dict: 'farfield' (raw result), 'scatterogram' (N_θ×N_φ×3 sRGB), 'lambda' (nm).
        """
        # Run getresult inside eval() so Lumerical's script engine computes all
        # frequencies silently — avoids the "Select frequency" GUI dialog that
        # appears when calling getresult() directly from Python with hide=False.
        self.fdtd.eval(
            f'_ff = getresult("{monitor_name}", "farfield");'
            f'_ff_E2 = _ff.E2;'
            f'_ff_lambda = _ff.lambda;'
        )
        e2 = self.fdtd.getv("_ff_E2")
        wavelengths_nm = self.fdtd.getv("_ff_lambda").flatten() * 1e9
        n_freq = len(wavelengths_nm)

        # Lumerical may return E2 as (N_theta, N_phi, 1, N_freq) or transposed.
        # Ensure the last axis is the frequency axis.
        print(f"[DEBUG] E2 raw shape: {e2.shape}, N_freq: {n_freq}")
        if e2.ndim == 4 and e2.shape[3] != n_freq and e2.shape[0] == n_freq:
            # (N_freq, N_phi, 1, N_theta) → (N_theta, N_phi, 1, N_freq)
            e2 = e2.transpose(3, 1, 2, 0)
        elif e2.ndim == 3 and e2.shape[2] == n_freq:
            # (N_theta, N_phi, N_freq) → add singleton polarisation dim
            e2 = e2[:, :, np.newaxis, :]
        elif e2.ndim == 3 and e2.shape[0] == n_freq:
            e2 = e2.transpose(2, 1, 0)[:, :, np.newaxis, :]

        n_theta_out, n_phi_out = e2.shape[0], e2.shape[1]

        # Per-angle intensity for brightness modulation (sum over all frequencies).
        # This preserves the radiation pattern while keeping colour information.
        intensity = np.sum(e2[:, :, 0, :], axis=-1)          # (N_theta, N_phi)
        intensity_norm = intensity / (intensity.max() or 1.0)

        scatterogram = np.zeros((n_theta_out, n_phi_out, 3))
        for i in range(n_theta_out):
            for j in range(n_phi_out):
                spd = e2[i, j, 0, :].flatten()
                spd_max = spd.max() or 1.0
                # Normalise per-angle to get spectral SHAPE (hue), then
                # scale brightness by the total power at this angle so the
                # radiation pattern is preserved.
                color = self._spectrum_to_srgb(wavelengths_nm, spd / spd_max)
                scatterogram[i, j] = color * intensity_norm[i, j]

        print(f"[OK] Far-field scatterogram computed ({n_theta_out}x{n_phi_out} angular points).")
        return {"farfield": e2, "scatterogram": scatterogram, "lambda": wavelengths_nm}

    def _spectrum_to_srgb(self, wavelengths, spd, step=1):
        """
        Convert a spectral power distribution to a clipped sRGB triplet.

        Args:
            wavelengths (array-like): Wavelengths in nm.
            spd (array-like): Spectral power values (same length as wavelengths).
            step (int): Resampling grid spacing in nm.

        Returns:
            np.ndarray: [R, G, B] in [0, 1].
        """
        target_wl = np.arange(380, 781, step)
        sd = colour.SpectralDistribution(np.interp(target_wl, wavelengths, spd), target_wl)
        XYZ = colour.sd_to_XYZ(
            sd,
            cmfs=colour.MSDS_CMFS["CIE 1931 2 Degree Standard Observer"],
            illuminant=colour.SDS_ILLUMINANTS["D65"],
        )
        return np.clip(colour.XYZ_to_sRGB(XYZ / 100.0), 0.0, 1.0)