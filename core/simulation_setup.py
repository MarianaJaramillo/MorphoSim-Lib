"""Lumerical FDTD simulation setup, execution, and post-processing.

Classes
-------
LumericalSimulation — wraps a lumapi.FDTD session and provides high-level
    methods for material definition, geometry import, FDTD region / source /
    monitor configuration, result extraction, far-field projection, and
    data export.

All spatial dimensions handled internally are in micrometres (µm) and
converted to metres before being passed to the Lumerical API.
"""

import os

import colour
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _moving_average(data: np.ndarray, window: int) -> np.ndarray:
    """Apply a uniform 1-D moving average (box filter) to *data*.

    Args:
        data   (np.ndarray): 1-D array of floats.
        window (int)       : Number of samples in the sliding window.
            Values < 1 return *data* unchanged.

    Returns:
        np.ndarray: Smoothed array of the same length (``mode='same'``).
    """
    if window < 1:
        return data
    kernel = np.ones(window) / window
    return np.convolve(data, kernel, mode='same')


class LumericalSimulation:
    def __init__(self, fdtd_session, config):
        """
        Initialize a LumericalSimulation object with the given FDTD session and configuration.
        Args:
            fdtd_session: The active Lumerical FDTD session (lumapi.FDTD()).
            config (dict): Configuration dictionary for the simulation and geometry.
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
        import numpy as np  # Make sure it's imported

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
        try:
            # First, make sure the file exists (Python check)
            if not os.path.exists(stl_file_path):
                print(f"[ERROR] The file does not exist at the path: {stl_file_path}")
                return

            self.fdtd.stlimport(stl_file_path, 1e-6)
            self.fdtd.set("name", "Morpho_Structure")
            self.fdtd.set("material", "Chitin")

            print(f"[OK] Import completed for: {stl_file_path}")

        except Exception as e:
            print(f"Specific error in import: {e}")

    # --- BLOCK 2: SCENARIO (FDTD Region and Source) ---

    def setup_fdtd_region(self, illumination_theta_deg=0.0):
        """
        Configure the FDTD simulation region, including boundaries, dimensions, and mesh settings.

        Args:
            illumination_theta_deg (float): Polar angle of incidence (degrees)
                that will be used by add_source(). Needed here too because it
                decides the boundary condition on x/y:
                  - 0 deg  -> Periodic BC (fields are truly periodic).
                  - != 0   -> Bloch BC required, since an angled plane wave on
                    a periodic structure has a phase shift between unit cells
                    (Periodic BC would silently give wrong results — see
                    "Periodic boundary conditions in FDTD and MODE", Ansys
                    Optics docs). "set based on source angle" is enabled so
                    Lumerical derives kx/ky/kz from whatever source angle is
                    configured in add_source().

        NOTE (periodic boundary conditions): x/y use Periodic or Bloch BC, which
        means the simulation models a single unit cell repeated to infinity. The
        far field computed from this monitor will therefore always show DISCRETE
        diffraction orders (broadened by the 'periods' argument in farfield3d),
        never a continuous diffuse halo like in disordered real scales. That is
        expected with this setup and is a separate, deliberate scope decision —
        not something the far-field code below can or should "fix".

        NOTE (broadband oblique incidence): with Bloch BC + a regular plane
        wave, the actual injection angle drifts with wavelength across a
        broadband scan — only the angle at the source's center wavelength
        matches illumination_theta_deg exactly. If you need a FIXED angle
        across the whole 380-800nm scan, use add_source(..., use_bfast=True)
        (Broadband Fixed Angle Source Technique), which keeps the angle
        constant for every frequency at the cost of being usable with only a
        single plane-wave source per simulation.
        """
        fdtd_region = self.fdtd.addfdtd()

        # 1. Geometry Parameters
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])
        substrate_height = self.config['substrate_thickness_along_z']
        substrate_gap = self.config['air_gap_below_substrate_along_z']

        # 2. Dimensions and Position
        fdtd_region.x_span = self.period_x * 1e-6
        fdtd_region.y_span = (self.depth_y - 0.1) * 1e-6

        z_min = -(substrate_height + substrate_gap + 0.3)
        z_max = ridge_height + 2.5
        fdtd_region.z_span = (z_max - z_min) * 1e-6
        fdtd_region.x, fdtd_region.y = 0, (self.depth_y / 2) * 1e-6
        fdtd_region.z = ((z_max + z_min) / 2) * 1e-6

        # 3. Boundary Condition Logic
        # Bloch is required whenever the structure is inclined OR the
        # illumination is off-normal — both introduce a phase shift between
        # unit cells that Periodic BC cannot represent.
        needs_bloch = (
            self.config.get('inclination_angle_radians', 0) != 0
            or illumination_theta_deg != 0
        )
        boundary_condition = "Bloch" if needs_bloch else "Periodic"

        self.fdtd.set("x min bc", boundary_condition)
        self.fdtd.set("x max bc", boundary_condition)
        self.fdtd.set("y min bc", boundary_condition)
        self.fdtd.set("y max bc", boundary_condition)
        self.fdtd.set("z min bc", "PML")
        self.fdtd.set("z max bc", "PML")

        if boundary_condition == "Bloch":
            try:
                # Let Lumerical derive kx/ky/kz from add_source()'s angle
                # instead of having to set the Bloch vector manually.
                self.fdtd.set("set based on source angle", True)
            except Exception as e:
                print(f"[WARN] Could not set 'set based on source angle': {e}")

        if abs(illumination_theta_deg) > 40:
            # Ansys recommends the 'Steep angle' PML profile whenever
            # Periodic/Bloch BC is combined with light travelling at steep
            # angles toward the PML boundaries (z min/max here) — relevant
            # both for steep injection and for steep diffraction orders.
            try:
                self.fdtd.set("pml profile", "Steep angle")
                print(f"[INFO] |theta|={illumination_theta_deg:g}deg > 40deg: "
                      f"PML profile switched to 'Steep angle'.")
            except Exception as e:
                print(f"[WARN] Could not switch PML profile to 'Steep angle' "
                      f"(verify the property name/value in your Lumerical "
                      f"version's GUI if this matters): {e}")

        # 4. Resolution and Shutdown
        self.fdtd.setglobalmonitor("frequency points", 100)
        self.fdtd.set("auto shutoff min", 0.001)  # Stabilization
        self.fdtd.set("mesh accuracy", 2)

        print(f"[OK] FDTD configured with {boundary_condition} BC "
              f"(theta_inc={illumination_theta_deg:g}deg) and 100 frequency points.")

    def add_source(self, polarization="TM", theta_deg=0.0, phi_deg=0.0, use_bfast=False):
        """
        Add a parametric source to the simulation, positioned above the ridge tip.

        Args:
            polarization (str): 'TE' (0 deg), 'TM' (90 deg), or a numeric angle
                in degrees (e.g. 45). Each call configures a SINGLE coherent
                linear polarization. To obtain physically correct unpolarized
                far-field results you must run two separate simulations with
                orthogonal polarizations (e.g. 'TE' and 'TM') and combine the
                resulting far fields incoherently with
                LumericalSimulation.combine_incoherent — see that method's
                docstring.
            theta_deg (float): Polar angle of incidence in degrees (0 = normal
                incidence, along -z given direction='Backward'). Requires
                setup_fdtd_region(illumination_theta_deg=theta_deg) to have
                been called with the SAME value, so the x/y boundary
                conditions are switched to Bloch consistently.
            phi_deg (float): Azimuthal angle of incidence in degrees. Not yet
                exposed as a user-facing control in main.py — kept at 0 by
                default; the plumbing is here for when that's needed.
            use_bfast (bool): If True, use the Broadband Fixed Angle Source
                Technique so theta_deg stays constant across the ENTIRE
                380-800nm scan (instead of drifting with wavelength, which is
                what happens with a regular Bloch/periodic plane wave at
                non-zero theta_deg). Only valid with a single plane-wave
                source per simulation, and overrides the x/y boundary
                conditions internally even though they're still nominally set
                to Bloch in setup_fdtd_region.
        """
        source = self.fdtd.addplane()
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])

        # Position: 0.2um above the tip
        source_z = ridge_height + 0.3

        source.x_span = (self.period_x + 1) * 1e-6
        source.y_span = (self.depth_y + 1) * 1e-6
        source.x, source.y = 0, (self.depth_y / 2) * 1e-6
        source.z = source_z * 1e-6

        self.fdtd.set("injection axis", "z-axis")
        self.fdtd.set("direction", "Backward")
        self.fdtd.set("wavelength start", 380e-9)
        self.fdtd.set("wavelength stop", 800e-9)

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

        # Angle of incidence (polar/theta is the control requested; phi kept
        # at 0 for now, plumbed through for future use).
        self.fdtd.set("angle theta", float(theta_deg))
        self.fdtd.set("angle phi", float(phi_deg))

        if use_bfast:
            try:
                self.fdtd.set("plane wave type", "BFAST")
                print("[INFO] Source set to BFAST: angle of incidence will stay "
                      f"fixed at theta={theta_deg:g}deg across the full broadband scan.")
            except Exception as e:
                print(f"[WARN] Could not enable BFAST plane wave type: {e}")
        elif theta_deg != 0:
            try:
                self.fdtd.set("plane wave type", "Bloch/periodic")
            except Exception:
                pass
            print(f"[WARN] theta={theta_deg:g}deg with a regular Bloch/periodic "
                  f"plane wave: the ACTUAL injection angle will drift away from "
                  f"{theta_deg:g}deg as wavelength moves away from the source's "
                  f"center wavelength across this broadband scan. Pass "
                  f"use_bfast=True if you need a fixed angle for every "
                  f"wavelength in the spectrum.")

        self.fdtd.set("name", f"source_{polarization}_theta{theta_deg:g}")
        self.fdtd.set("amplitude", 1000000)  # Standard value (1V/m)

        print(f"[OK] {polarization} source injecting at {source_z:.2f}um, "
              f"theta={theta_deg:g}deg, phi={phi_deg:g}deg.")

    # --- BLOCK 3: MONITORS ---

    def add_monitors(self):
        """
        Add reflectance (R) and transmittance (T) monitors to the simulation with fixed names and positions.
        """
        ridge_height = self.config['number_of_layers'] * (self.config['chitin_layer_thickness'] + self.config['air_layer_thickness'])
        substrate_height = self.config['substrate_thickness_along_z']
        substrate_gap = self.config['air_gap_below_substrate_along_z']
        y_position = (self.depth_y / 2) * 1e-6

        # --- R MONITOR ---
        self.fdtd.addpower()
        self.fdtd.set("name", "R_monitor")  # <--- The name must go FIRST
        self.fdtd.set("monitor type", "2D Z-normal")

        # We use setnamed for dimensions for safety
        self.fdtd.setnamed("R_monitor", "x span", self.period_x * 1e-6)
        self.fdtd.setnamed("R_monitor", "y span", (self.depth_y - 0.1) * 1e-6)
        self.fdtd.setnamed("R_monitor", "x", 0)
        self.fdtd.setnamed("R_monitor", "y", y_position)
        self.fdtd.setnamed("R_monitor", "z", (ridge_height + 1.2) * 1e-6)

        # Activate E field components
        self.fdtd.setnamed("R_monitor", "output Ex", True)
        self.fdtd.setnamed("R_monitor", "output Ey", True)
        self.fdtd.setnamed("R_monitor", "output Ez", True)
        # Activate H field components — required for farfield3d far-field projection
        self.fdtd.setnamed("R_monitor", "output Hx", True)
        self.fdtd.setnamed("R_monitor", "output Hy", True)
        self.fdtd.setnamed("R_monitor", "output Hz", True)

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
            print(f"[DEBUG] Requesting 'T' result from {r_monitor}...")
            res_potencia = self.fdtd.getresult(r_monitor, "T")
            wavelengths = res_potencia['lambda'].flatten() * 1e9
            r_total_raw = np.abs(res_potencia['T'].flatten())

            if mode == "total":
                r_total_smooth = _moving_average(r_total_raw, window_size)
                print("[OK] Total mode processed.")
                return {
                    "lambda": wavelengths,
                    "R": r_total_smooth
                }

            elif mode in ["cross", "parallel"]:
                print(f"[DEBUG] Requesting field dataset 'E' from {r_monitor}...")
                try:
                    e_dataset = self.fdtd.getresult(r_monitor, "E")
                    e_matrix = e_dataset["E"]
                except Exception as e_get:
                    print(f"[CRITICAL ERROR] Could not obtain 'E' field: {e_get}")
                    raise

                ex_field = e_matrix[:, :, :, :, 0]
                ey_field = e_matrix[:, :, :, :, 1]

                if mode == "cross":
                    e_proj = (ex_field - ey_field) / np.sqrt(2)
                elif mode == "parallel":
                    e_proj = (ex_field + ey_field) / np.sqrt(2)

                i_proj = np.sum(np.abs(e_proj) ** 2, axis=(0, 1, 2)).flatten()
                i_total_fields = np.sum(np.abs(ex_field) ** 2 + np.abs(ey_field) ** 2, axis=(0, 1, 2)).flatten()

                fraction_proj = np.divide(
                    i_proj,
                    i_total_fields,
                    out=np.zeros_like(i_proj),
                    where=i_total_fields != 0
                )

                r_proj_raw = r_total_raw * fraction_proj
                r_proj_smooth = _moving_average(r_proj_raw, window_size)

                print(f"[OK] Reflectance with {'crossed' if mode=='cross' else 'parallel'} polarizer (interference method) calculated.")

                return {
                    "lambda": wavelengths,
                    "R": r_proj_smooth,
                    "R_total": _moving_average(r_total_raw, window_size),
                    "polarization_fraction": fraction_proj
                }

        except Exception as e_general:
            print(f"\n[GENERAL FAILURE IN ANALYSIS]: {e_general}")
            import traceback
            traceback.print_exc()
            return None

    def analyze_results_angle_resolved(self, r_monitor="R_monitor",
                                        detection_theta_deg=0.0, detection_phi_deg=0.0,
                                        detection_halfangle_deg=5.0,
                                        na=150, nb=150, window_size=15):
        """
        Angle-resolved ("goniometric") reflectance spectrum: instead of
        analyze_results' total power crossing R_monitor (integrated over the
        ENTIRE hemisphere), this points a virtual detector at a specific
        (detection_theta_deg, detection_phi_deg) direction with its own
        aperture (detection_halfangle_deg, like a numerical aperture / solid
        angle), and reports only the fraction of reflected power that lands
        inside that cone, at every simulated wavelength.

        Method, per wavelength:
          1. E2(ux,uy) -- far-field projection. Tries the Ansys farfield3d
             script command ONCE (single test call); if that fails for any
             reason in this Lumerical session/environment, falls back to the
             angular-spectrum (FFT) projection already used elsewhere in this
             file (_far_field_fft / _grating_slice) for the REST of the scan,
             instead of re-testing farfield3d on every wavelength.
          2. cone_power / total_power -- integrated with _integrate_cone, a
             pure-Python replica of the farfield3dintegrate script command
             (used instead of that command directly, since this method no
             longer assumes farfield3d-family commands are available).
          3. R_detected = (cone_power / total_power) * T_total, where T_total
             is the standard normalized reflectance from the 'T' result (same
             quantity analyze_results' 'total' mode uses), so R_detected
             stays in the same units/normalization (fraction of source power).

        Args:
            r_monitor (str): 2D Z-normal power monitor.
            detection_theta_deg (float): Polar angle of the virtual detector
                (0 = specular/normal direction).
            detection_phi_deg (float): Azimuthal angle of the virtual
                detector. Not yet exposed in main.py — kept at 0 by default.
            detection_halfangle_deg (float): Half-angle (aperture/NA) of the
                virtual detector's collection cone, in degrees.
            na, nb (int): Angular grid resolution used internally for the
                far-field projection at each wavelength.
            window_size (int): Moving-average smoothing window, same
                convention as analyze_results.

        Returns:
            dict: 'lambda', 'R' (smoothed, angle-resolved),
                  'detection_theta_deg', 'detection_phi_deg',
                  'detection_halfangle_deg', 'method' ('farfield3d' or 'fft').
        """
        print(f"[DEBUG] Requesting 'T' result from {r_monitor}...")
        res_potencia = self.fdtd.getresult(r_monitor, "T")
        wavelengths = res_potencia['lambda'].flatten() * 1e9
        T_total = np.abs(res_potencia['T'].flatten())
        n_freq = len(wavelengths)

        n_periods = 50  # same convergence rationale as get_far_field_at_wavelength
        R_detected = np.zeros(n_freq, dtype=float)

        print(f"[OK] Angle-resolved scan: detector at theta={detection_theta_deg:g}deg, "
              f"phi={detection_phi_deg:g}deg, half-angle={detection_halfangle_deg:g}deg "
              f"over {n_freq} wavelengths...")

        # Decide the projection method ONCE up front (same pattern as
        # get_far_field_colored), instead of re-attempting farfield3d on
        # every one of the 100 wavelengths.
        use_ff3d = False
        try:
            self.fdtd.eval(
                f'_artest = farfield3d("{r_monitor}", 1, {na}, {nb}, 1, {n_periods}, {n_periods});'
            )
            self.fdtd.getv("_artest")
            use_ff3d = True
            print("[OK] Angle-resolved projection: farfield3d")
        except Exception as e:
            print(f"[INFO] farfield3d unavailable in this session ({e!r}); "
                  f"using angular-spectrum (FFT) projection instead "
                  f"(same fallback method used by get_far_field_at_wavelength).")

        method = "farfield3d" if use_ff3d else "fft"

        for f_idx_0 in range(n_freq):
            f_idx_1 = f_idx_0 + 1  # 1-based for Lumerical script
            E2 = ux = uy = None

            if use_ff3d:
                try:
                    self.fdtd.eval(
                        f'_arE2 = farfield3d("{r_monitor}", {f_idx_1}, {na}, {nb}, '
                        f'1, {n_periods}, {n_periods});'
                    )
                    self.fdtd.eval(f'_arux = farfieldux("{r_monitor}", {f_idx_1});')
                    self.fdtd.eval(f'_aruy = farfielduy("{r_monitor}", {f_idx_1});')
                    E2 = self.fdtd.getv("_arE2")
                    ux = self.fdtd.getv("_arux").flatten()
                    uy = self.fdtd.getv("_aruy").flatten()
                    if E2.shape != (len(ux), len(uy)):
                        E2 = E2.T
                except Exception as e:
                    print(f"[WARN] farfield3d failed at f_idx={f_idx_1} "
                          f"(lambda={wavelengths[f_idx_0]:.1f} nm): {e!r}; "
                          f"using FFT fallback for this point.")
                    E2 = None

            if E2 is None:
                E2, ux, uy = self._far_field_fft(
                    r_monitor, f_idx_0, wavelengths[f_idx_0], na, nb, projection="total"
                )

            cone_power, total_power = self._integrate_cone(
                E2, ux, uy, detection_theta_deg, detection_phi_deg, detection_halfangle_deg
            )
            fraction = (cone_power / total_power) if total_power != 0 else 0.0
            R_detected[f_idx_0] = fraction * T_total[f_idx_0]

            if (f_idx_0 + 1) % 20 == 0 or f_idx_0 == n_freq - 1:
                print(f"  [{f_idx_0 + 1:3d}/{n_freq}] lambda = {wavelengths[f_idx_0]:.1f} nm  "
                      f"R_detected = {R_detected[f_idx_0]:.4f}")

        R_smooth = _moving_average(R_detected, window_size)
        print(f"[OK] Angle-resolved reflectance computed [method: {method}].")

        return {
            "lambda": wavelengths,
            "R": R_smooth,
            "detection_theta_deg": detection_theta_deg,
            "detection_phi_deg": detection_phi_deg,
            "detection_halfangle_deg": detection_halfangle_deg,
            "method": method,
        }

    @staticmethod
    def _integrate_cone(E2, ux, uy, theta0_deg, phi0_deg, halfangle_deg):
        """
        Pure-Python replica of the Ansys farfield3dintegrate script command:
        integrates E2(ux,uy) over a cone centered at (theta0_deg, phi0_deg)
        with half-angle halfangle_deg, and also returns the integral over the
        full hemisphere for normalization.

        Used as a self-contained fallback so angle-resolved detection doesn't
        depend on farfield3d/farfield3dintegrate being available, since the
        former has been observed to fail in some Lumerical sessions/licenses
        without a clear underlying error message.

        Uses the standard direction-cosine solid-angle element
        dOmega = dux*duy / cos(theta), with cos(theta) floored to avoid
        blow-up exactly at the grazing horizon (theta -> 90 deg).

        Returns:
            (cone_power, total_power): both plain floats.
        """
        UX, UY = np.meshgrid(ux, uy, indexing='ij')
        sin2 = np.clip(UX ** 2 + UY ** 2, 0.0, 1.0)
        theta = np.arcsin(np.sqrt(sin2))   # radians
        phi = np.arctan2(UY, UX)           # radians

        theta0 = np.radians(theta0_deg)
        phi0 = np.radians(phi0_deg)
        cos_ang = (np.sin(theta) * np.sin(theta0) * np.cos(phi - phi0)
                   + np.cos(theta) * np.cos(theta0))
        angular_dist_deg = np.degrees(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
        mask = angular_dist_deg <= halfangle_deg

        dux = float(ux[1] - ux[0]) if len(ux) > 1 else 1.0
        duy = float(uy[1] - uy[0]) if len(uy) > 1 else 1.0
        cos_theta = np.clip(np.cos(theta), 1e-3, 1.0)
        dOmega = (dux * duy) / cos_theta

        cone_power = float(np.sum(E2[mask] * dOmega[mask]))
        total_power = float(np.sum(E2 * dOmega))
        return cone_power, total_power

    def save_results(self, results, filename="reflectance_data.csv", folder="results/reflectance_data"):
        """
        Save the wavelength and reflectance data to a CSV file in the results folder.
        """
        try:
            df = pd.DataFrame({
                'wavelength_nm': results['lambda'],
                'reflectance': results['R']
            })
            if 'R_total' in results:
                df['reflectance_total'] = results['R_total']

            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            df.to_csv(path, index=False)
            print(f"[OK] Data saved successfully at: {path}")
        except Exception as e:
            print(f"[ERROR saving]: {e}")

    # =====================================================================
    # FAR FIELD
    #
    # IMPORTANT — polarization scope of every method below:
    # A single FDTD run (single LumericalSimulation instance / single .fsp)
    # only ever contains the field produced by whichever single coherent
    # source polarization you configured in add_source(). There is NO way
    # to recover true unpolarized (incoherent) illumination from one run's
    # field data, regardless of how Ex/Ey are recombined — Ex and Ey from a
    # single coherent source always carry a fixed phase relationship.
    #
    # Use:
    #   - get_far_field_at_wavelength / get_far_field_colored  -> far field
    #     for the single polarization that was actually simulated.
    #   - combine_incoherent                                   -> physically
    #     correct unpolarized far field, built by incoherently summing the
    #     results of TWO separate runs (e.g. polarization='TE' and
    #     polarization='TM').
    # =====================================================================

    def get_far_field_at_wavelength(self, wavelength_nm, monitor_name="R_monitor", na=150, nb=150,
                                     projection="total"):
        """
        Compute the far-field |E|^2 distribution at a single wavelength, for
        whatever single polarization was actually simulated in this run.

        Strategy:
          1. Primary  – farfield3d / farfieldux / farfielduy script commands
                        (requires E+H stored in the monitor). Valid here
                        because the FDTD region uses Periodic/Bloch BC in x/y.
          2. Fallback – Bloch-order (grating) projection computed from the
                        E field only, activated automatically if farfield3d
                        fails for any reason.

        Args:
            wavelength_nm (float): Target wavelength in nm.
            monitor_name (str): Name of the 2D Z-normal power monitor.
            na (int): Angular resolution along ux (default 150).
            nb (int): Angular resolution along uy (default 150).
            projection (str): Only used by the fallback method. 'total' (Ex+Ey,
                default) or 'TE' / 'cross' — see _grating_slice.

        Returns:
            dict: 'E2', 'ux', 'uy', 'theta', 'phi', 'wavelength_nm',
                  'wavelength_requested_nm', 'method' ('farfield3d' or 'fft').
        """
        try:
            wavelengths_m = self.fdtd.getdata(monitor_name, "lambda").flatten()
        except Exception:
            res_T = self.fdtd.getresult(monitor_name, "T")
            wavelengths_m = res_T['lambda'].flatten()

        wavelengths_nm_arr = wavelengths_m * 1e9

        f_index_0 = int(np.argmin(np.abs(wavelengths_nm_arr - wavelength_nm)))
        f_index_1 = f_index_0 + 1  # 1-based for Lumerical script
        actual_wl = float(wavelengths_nm_arr[f_index_0])
        print(f"[OK] Far field: {wavelength_nm:.1f} nm requested → "
              f"{actual_wl:.2f} nm used (f_index = {f_index_1} / {len(wavelengths_nm_arr)})")

        # Number of periods for farfield3d — per Ansys docs, projecting a
        # single unit cell produces aperture-diffraction artefacts. Specifying
        # N periods makes the projection represent a finite periodic array
        # (broadened discrete orders rather than delta functions).
        n_periods = 50  # periods in X and Y (50 is sufficient for convergence)

        E2, ux, uy, method = None, None, None, "farfield3d"
        try:
            self.fdtd.eval(f'_ff_E2 = farfield3d("{monitor_name}", {f_index_1}, {na}, {nb}, 1, {n_periods}, {n_periods});')
            self.fdtd.eval(f'_ff_ux = farfieldux("{monitor_name}", {f_index_1});')
            self.fdtd.eval(f'_ff_uy = farfielduy("{monitor_name}", {f_index_1});')
            E2 = self.fdtd.getv("_ff_E2")
            ux = self.fdtd.getv("_ff_ux").flatten()
            uy = self.fdtd.getv("_ff_uy").flatten()
            print("[OK] farfield3d projection completed.")
        except Exception as e_ff:
            print(f"[WARN] farfield3d failed: {e_ff!r}")
            print("[INFO] Falling back to Bloch-order (grating) projection …")
            E2, ux, uy = self._far_field_fft(
                monitor_name, f_index_0, actual_wl, na, nb, projection=projection
            )
            method = "fft"

        if E2.ndim == 2 and E2.shape != (len(ux), len(uy)):
            E2 = E2.T

        UX, UY = np.meshgrid(ux, uy, indexing='ij')
        sin2 = np.clip(UX ** 2 + UY ** 2, 0.0, 1.0)
        theta_deg = np.degrees(np.arcsin(np.sqrt(sin2)))
        phi_deg = np.degrees(np.arctan2(UY, UX))

        print(f"[OK] Far field map: {E2.shape[0]}×{E2.shape[1]} pts, "
              f"λ = {actual_wl:.2f} nm  [method: {method}]")
        return {
            "E2": E2,
            "ux": ux,
            "uy": uy,
            "theta": theta_deg,
            "phi": phi_deg,
            "wavelength_nm": actual_wl,
            "wavelength_requested_nm": wavelength_nm,
            "method": method,
        }

    def _far_field_fft(self, monitor_name, f_index_0, wavelength_nm, na=150, nb=150, projection="total"):
        """
        Periodic grating far-field fallback (used only if farfield3d fails).
        Returns E2 on a fixed ux/uy ∈ [-1, 1] grid.
        """
        e_data = self.fdtd.getresult(monitor_name, "E")
        x = e_data['x'].flatten()
        y = e_data['y'].flatten()
        wl_m = wavelength_nm * 1e-9
        Lx = float(np.abs(x[-1] - x[0])) + (float(np.abs(x[1] - x[0])) if len(x) > 1 else 1e-8)
        Ly = float(np.abs(y[-1] - y[0])) + (float(np.abs(y[1] - y[0])) if len(y) > 1 else 1e-8)
        ux_out = np.linspace(-1.0, 1.0, na)
        uy_out = np.linspace(-1.0, 1.0, nb)
        E2_out = self._grating_slice(e_data, f_index_0, wl_m, Lx, Ly, na, nb, ux_out, uy_out,
                                      projection=projection)
        return E2_out, ux_out, uy_out

    def _grating_slice(self, e_data, f_index_0, wl_m, Lx, Ly, na, nb, ux_out, uy_out,
                        projection='total'):
        """
        Periodic-structure far-field via grating-order projection.

        projection='total' : |Ex_mn|² + |Ey_mn|²  — total intensity of the
            single polarization that was simulated. This is the physically
            meaningful default for a single coherent run.
        projection='TE'    : |Ex_mn|² only. Only use this if you have a
            specific, verified reason to believe Ex alone carries the signal
            of interest for your structure/angle range — don't rely on it as
            a silent default.
        projection='cross' : |Ex_mn - Ey_mn|²/2   — crossed polarizers.
        """
        E_mat = e_data['E']
        if E_mat.ndim == 5:
            Ex = E_mat[:, :, 0, f_index_0, 0]
            Ey = E_mat[:, :, 0, f_index_0, 1]
        elif E_mat.ndim == 4:
            Ex = E_mat[:, :, f_index_0, 0]
            Ey = E_mat[:, :, f_index_0, 1]
        else:
            raise ValueError(f"Unexpected E field shape: {E_mat.shape}")

        Nx, Ny = Ex.shape
        # FFT over one unit cell → Bloch order amplitudes
        Ex_k = np.fft.fft2(Ex) / (Nx * Ny)
        Ey_k = np.fft.fft2(Ey) / (Nx * Ny)

        # Grating-order direction cosines
        m_max = int(np.ceil(Lx / wl_m)) + 1
        n_max = int(np.ceil(Ly / wl_m)) + 1
        m_arr = np.arange(-m_max, m_max + 1)
        n_arr = np.arange(-n_max, n_max + 1)

        dux = 2.0 / (na - 1) if na > 1 else 1.0
        duy = 2.0 / (nb - 1) if nb > 1 else 1.0
        sigma_x = dux * 3.0
        sigma_y = duy * 3.0
        half_w = 9

        E2_out = np.zeros((na, nb), dtype=float)

        for m in m_arr:
            ux_m = m * wl_m / Lx
            if abs(ux_m) > 1.0:
                continue
            mi = int(m) % Nx
            for n in n_arr:
                uy_n = n * wl_m / Ly
                if ux_m ** 2 + uy_n ** 2 > 1.0:
                    continue
                ni = int(n) % Ny
                if projection == 'TE':
                    amp2 = float(abs(Ex_k[mi, ni]) ** 2)
                elif projection == 'cross':
                    amp2 = float(abs(Ex_k[mi, ni] - Ey_k[mi, ni]) ** 2) * 0.5
                else:  # 'total'
                    amp2 = float(abs(Ex_k[mi, ni]) ** 2 + abs(Ey_k[mi, ni]) ** 2)
                if amp2 == 0.0:
                    continue
                ix_c = (ux_m - ux_out[0]) / (ux_out[-1] - ux_out[0]) * (na - 1)
                iy_c = (uy_n - uy_out[0]) / (uy_out[-1] - uy_out[0]) * (nb - 1)
                ix0 = max(0, int(ix_c) - half_w)
                ix1 = min(na, int(ix_c) + half_w + 1)
                iy0 = max(0, int(iy_c) - half_w)
                iy1 = min(nb, int(iy_c) + half_w + 1)
                ii = np.arange(ix0, ix1)
                jj = np.arange(iy0, iy1)
                gx = np.exp(-0.5 * ((ii - ix_c) * dux / sigma_x) ** 2)
                gy = np.exp(-0.5 * ((jj - iy_c) * duy / sigma_y) ** 2)
                E2_out[np.ix_(ii, jj)] += amp2 * np.outer(gx, gy)

        return E2_out

    def _bilinear_interp(self, E2, x_in, y_in, x_out, y_out):
        """
        Vectorized bilinear interpolation of E2[x_in × y_in] onto
        the (x_out × y_out) grid. Points outside the input range → 0.
        """
        ix = np.clip(np.searchsorted(x_in, x_out) - 1, 0, len(x_in) - 2)
        iy = np.clip(np.searchsorted(y_in, y_out) - 1, 0, len(y_in) - 2)
        denom_x = x_in[ix + 1] - x_in[ix]
        wx1 = np.clip(
            np.where(denom_x != 0, (x_out - x_in[ix]) / denom_x, 0.5), 0.0, 1.0
        )
        wx0 = 1.0 - wx1
        denom_y = y_in[iy + 1] - y_in[iy]
        wy1 = np.clip(
            np.where(denom_y != 0, (y_out - y_in[iy]) / denom_y, 0.5), 0.0, 1.0
        )
        wy0 = 1.0 - wy1
        return (
            wx0[:, None] * wy0[None, :] * E2[np.ix_(ix,     iy    )] +
            wx0[:, None] * wy1[None, :] * E2[np.ix_(ix,     iy + 1)] +
            wx1[:, None] * wy0[None, :] * E2[np.ix_(ix + 1, iy    )] +
            wx1[:, None] * wy1[None, :] * E2[np.ix_(ix + 1, iy + 1)]
        )

    @staticmethod
    def combine_incoherent(far_field_pol1, far_field_pol2):
        """
        Physically correct unpolarized far field: incoherently combine the
        far-field results of TWO INDEPENDENT runs with orthogonal source
        polarizations (e.g. one run with add_source('TE'), one with
        add_source('TM')), each producing its own .fsp / E2 via
        get_far_field_at_wavelength.

        Unpolarized light = incoherent mixture of two orthogonal linear
        polarizations, i.e. I_unpol = |E_pol1|^2 + |E_pol2|^2, where each
        term comes from its OWN independent simulation. This is different
        from (and not derivable from) splitting Ex/Ey out of a single
        coherent run.

        Typical usage in your workflow:
            sim_TE = LumericalSimulation(fdtd, config)
            ... setup + add_source('TE') + run ...
            ff_TE = sim_TE.get_far_field_at_wavelength(450)

            # new FDTD session/run
            sim_TM = LumericalSimulation(fdtd, config)
            ... setup + add_source('TM') + run ...
            ff_TM = sim_TM.get_far_field_at_wavelength(450)

            ff_unpol = LumericalSimulation.combine_incoherent(ff_TE, ff_TM)

        Args:
            far_field_pol1 (dict): Output of get_far_field_at_wavelength for
                polarization 1.
            far_field_pol2 (dict): Output of get_far_field_at_wavelength for
                polarization 2, on the SAME (ux, uy) grid (i.e. same na, nb
                passed to both calls).

        Returns:
            dict: same shape as the inputs, with 'E2' = sum, and
                  'method' = 'incoherent_sum(<m1>, <m2>)'.
        """
        ux1, uy1 = far_field_pol1["ux"], far_field_pol1["uy"]
        ux2, uy2 = far_field_pol2["ux"], far_field_pol2["uy"]
        if ux1.shape != ux2.shape or not np.allclose(ux1, ux2) or not np.allclose(uy1, uy2):
            raise ValueError(
                "combine_incoherent requires both far fields to share the same "
                "(ux, uy) grid — pass the same na/nb to both "
                "get_far_field_at_wavelength calls."
            )
        if abs(far_field_pol1["wavelength_nm"] - far_field_pol2["wavelength_nm"]) > 1e-6:
            print(f"[WARN] combine_incoherent: wavelengths differ "
                  f"({far_field_pol1['wavelength_nm']:.2f} nm vs "
                  f"{far_field_pol2['wavelength_nm']:.2f} nm) — combining anyway.")

        E2_sum = far_field_pol1["E2"] + far_field_pol2["E2"]
        out = dict(far_field_pol1)
        out["E2"] = E2_sum
        out["method"] = f"incoherent_sum({far_field_pol1['method']}, {far_field_pol2['method']})"
        return out

    def get_far_field(self, monitor_name="R_monitor", n_theta=100, n_phi=100):
        """
        Compute the far-field scatterogram from a Lumerical monitor.

        For each angular point (θ, φ), the full spectral power distribution
        across all simulated wavelengths is converted to a single sRGB colour
        using _spectrum_to_srgb — so the colour reflects the entire visible range.

        NOTE: same single-polarization scope as the rest of this section — see
        the block comment above get_far_field_at_wavelength.

        Args:
            monitor_name (str): Monitor to query (must have far-field projection enabled).
            n_theta (int): Number of polar angle points for the far-field projection.
            n_phi (int): Number of azimuthal angle points for the far-field projection.

        Returns:
            dict: 'farfield' (raw result), 'scatterogram' (N_θ×N_φ×3 sRGB), 'lambda' (nm).
        """
        self.fdtd.eval(
            f'_ff = getresult("{monitor_name}", "farfield");'
            f'_ff_E2 = _ff.E2;'
            f'_ff_lambda = _ff.lambda;'
        )
        e2 = self.fdtd.getv("_ff_E2")
        wavelengths_nm = self.fdtd.getv("_ff_lambda").flatten() * 1e9
        n_freq = len(wavelengths_nm)

        print(f"[DEBUG] E2 raw shape: {e2.shape}, N_freq: {n_freq}")
        if e2.ndim == 4 and e2.shape[3] != n_freq and e2.shape[0] == n_freq:
            e2 = e2.transpose(3, 1, 2, 0)
        elif e2.ndim == 3 and e2.shape[2] == n_freq:
            e2 = e2[:, :, np.newaxis, :]
        elif e2.ndim == 3 and e2.shape[0] == n_freq:
            e2 = e2.transpose(2, 1, 0)[:, :, np.newaxis, :]

        n_theta_out, n_phi_out = e2.shape[0], e2.shape[1]

        intensity = np.sum(e2[:, :, 0, :], axis=-1)
        intensity_norm = intensity / (intensity.max() or 1.0)

        scatterogram = np.zeros((n_theta_out, n_phi_out, 3))
        for i in range(n_theta_out):
            for j in range(n_phi_out):
                spd = e2[i, j, 0, :].flatten()
                spd_max = spd.max() or 1.0
                color = self._spectrum_to_srgb(wavelengths_nm, spd / spd_max)
                scatterogram[i, j] = color * intensity_norm[i, j]

        print(f"[OK] Far-field scatterogram computed ({n_theta_out}x{n_phi_out} angular points).")
        return {"farfield": e2, "scatterogram": scatterogram, "lambda": wavelengths_nm}

    def get_far_field_colored(self, monitor_name="R_monitor", na=150, nb=150,
                              wl_start=380, wl_stop=780, wl_step=10, projection="total"):
        """
        Build a colour-mapped far-field scatterogram covering the full hemisphere
        (θ ∈ [0°, 90°]), for the single polarization that was simulated.

        For each angular point (ux, uy) the spectral power distribution is
        converted to sRGB via CIE 1931 CMFs (vectorised — no per-pixel loop).
        Diffraction bands appear as coloured arcs at their correct angles.

        NOTE on normalization: field/power monitor results are already
        returned in Lumerical's default cwnorm state, i.e. already divided by
        the source spectrum. No extra division by sourcepower(f) is applied
        here — doing so would double-correct the spectrum. If you ever switch
        the simulation to nonorm() explicitly, you would need to reintroduce
        an equivalent correction.

        Args:
            monitor_name (str): 2D Z-normal power monitor.
            na (int)         : Angular grid points along ux (default 150).
            nb (int)         : Angular grid points along uy (default 150).
            wl_start (float) : First wavelength in nm (default 380).
            wl_stop  (float) : Last  wavelength in nm (default 780).
            wl_step  (float) : Step in nm (default 10).
            projection (str) : Only used by the fallback method ('total' default).

        Returns:
            dict: 'rgb' (na×nb×3), 'E2_cube' (na×nb×N_wl),
                  'ux', 'uy', 'wavelengths'.
        """
        # ── 1. Wavelength axis ──────────────────────────────────────────────
        try:
            wavelengths_m = self.fdtd.getdata(monitor_name, "lambda").flatten()
        except Exception:
            wavelengths_m = self.fdtd.getresult(monitor_name, "T")['lambda'].flatten()
        wavelengths_sim_nm = wavelengths_m * 1e9

        wl_start = max(wl_start, float(wavelengths_sim_nm.min()))
        wl_stop = min(wl_stop, float(wavelengths_sim_nm.max()))
        scan_wls = np.arange(wl_start, wl_stop + wl_step * 0.5, wl_step)
        N_wl = len(scan_wls)
        print(f"[OK] Color far field: {N_wl} wavelengths "
              f"({wl_start:.0f}–{wl_stop:.0f} nm, step {wl_step:.0f} nm)")

        # ── 2. Detect farfield3d availability (test first wavelength) ───────
        f0_test = int(np.argmin(np.abs(wavelengths_sim_nm - scan_wls[0]))) + 1
        use_ff3d = False
        ux_ff3d = None
        uy_ff3d = None
        n_periods = 50
        try:
            self.fdtd.eval(
                f'_test = farfield3d("{monitor_name}", {f0_test}, {na}, {nb}, 1, {n_periods}, {n_periods});'
            )
            self.fdtd.getv("_test")
            use_ff3d = True
            print("[OK] Projection: farfield3d")
        except Exception:
            print("[INFO] Projection: Bloch-order (grating) fallback")

        # ── 3. Fixed output grid ∈ [-1, 1]  (both methods) ─────────────────
        ux_out = np.linspace(-1.0, 1.0, na)
        uy_out = np.linspace(-1.0, 1.0, nb)

        # ── 4. Pre-load E field ONCE when using grating fallback ───────────
        e_cache = Lx_c = Ly_c = None
        if not use_ff3d:
            print("[INFO] Loading field data from monitor (single call)...")
            e_cache = self.fdtd.getresult(monitor_name, "E")
            x_arr = e_cache['x'].flatten()
            y_arr = e_cache['y'].flatten()
            Lx_c = float(abs(x_arr[-1] - x_arr[0])) + (float(abs(x_arr[1] - x_arr[0])) if len(x_arr) > 1 else 1e-8)
            Ly_c = float(abs(y_arr[-1] - y_arr[0])) + (float(abs(y_arr[1] - y_arr[0])) if len(y_arr) > 1 else 1e-8)

        # ── 5. Build E2 cube ────────────────────────────────────────────────
        E2_cube = np.zeros((na, nb, N_wl), dtype=float)
        used_wls = []

        for i, target_wl in enumerate(scan_wls):
            f_idx_0 = int(np.argmin(np.abs(wavelengths_sim_nm - target_wl)))
            f_idx_1 = f_idx_0 + 1
            actual_wl = float(wavelengths_sim_nm[f_idx_0])
            used_wls.append(actual_wl)

            if use_ff3d:
                try:
                    self.fdtd.eval(
                        f'_ffc = farfield3d("{monitor_name}", {f_idx_1}, {na}, {nb}, 1, {n_periods}, {n_periods});'
                    )
                    E2_s = self.fdtd.getv("_ffc")
                    if i == 0:  # get ux/uy grid once
                        self.fdtd.eval(
                            f'_ffc_ux = farfieldux("{monitor_name}", {f_idx_1});'
                            f'_ffc_uy = farfielduy("{monitor_name}", {f_idx_1});'
                        )
                        ux_ff3d = self.fdtd.getv("_ffc_ux").flatten()
                        uy_ff3d = self.fdtd.getv("_ffc_uy").flatten()
                    if E2_s.shape != (na, nb):
                        E2_s = E2_s.T
                    # Resample onto fixed [-1,1] grid for consistency
                    E2_s = self._bilinear_interp(E2_s, ux_ff3d, uy_ff3d, ux_out, uy_out)
                except Exception:
                    if e_cache is None:
                        e_cache = self.fdtd.getresult(monitor_name, "E")
                        x_arr = e_cache['x'].flatten()
                        y_arr = e_cache['y'].flatten()
                        Lx_c = float(abs(x_arr[-1] - x_arr[0])) + (float(abs(x_arr[1] - x_arr[0])) if len(x_arr) > 1 else 1e-8)
                        Ly_c = float(abs(y_arr[-1] - y_arr[0])) + (float(abs(y_arr[1] - y_arr[0])) if len(y_arr) > 1 else 1e-8)
                    E2_s = self._grating_slice(
                        e_cache, f_idx_0, actual_wl * 1e-9, Lx_c, Ly_c, na, nb, ux_out, uy_out,
                        projection=projection
                    )
            else:
                E2_s = self._grating_slice(
                    e_cache, f_idx_0, actual_wl * 1e-9, Lx_c, Ly_c, na, nb, ux_out, uy_out,
                    projection=projection
                )

            E2_cube[:, :, i] = E2_s
            if (i + 1) % 10 == 0 or i == N_wl - 1:
                print(f"  [{i+1:2d}/{N_wl}] λ = {actual_wl:.1f} nm")

        used_wls = np.array(used_wls)

        # NOTE: no sourcepower(f) re-normalization here on purpose.
        # Monitor data is already cwnorm-normalized by Lumerical by default
        # (see Understanding frequency domain CW normalization in the Ansys
        # docs) — dividing by sourcepower again would double-correct the
        # spectrum and distort the colour balance (artificially boosting the
        # wavelengths where the source pulse is weakest).

        rgb = LumericalSimulation._colorize_E2_cube(E2_cube, used_wls)

        print(f"[OK] Color far field ready: {na}×{nb} px, {N_wl} wavelengths.")
        return {
            "rgb": rgb,
            "E2_cube": E2_cube,
            "ux": ux_out,
            "uy": uy_out,
            "wavelengths": used_wls,
        }

    @staticmethod
    def _colorize_E2_cube(E2_cube, wavelengths_nm):
        """
        Convert an (na, nb, N_wl) intensity cube into an (na, nb, 3) sRGB image.

        Correct colorimetric order of operations:
          1. Integrate the spectral power distribution E2(λ) against the CIE
             CMFs in LINEAR XYZ space -> one XYZ triplet per pixel.
          2. Normalize each pixel's XYZ by its own Y (luminance) to get pure
             hue/chromaticity, independent of total brightness.
          3. Convert to sRGB and clip ONCE per pixel, at the very end.
          4. Re-apply a gamma-compressed total-power brightness so weak
             diffraction orders stay visible next to the dominant peak.

        A previous version of this function instead converted EACH
        wavelength to sRGB individually (with its own clip(0,1)) and then
        linearly averaged those already-gamma-corrected, already-clipped sRGB
        values weighted by E2. That is colorimetrically wrong for two
        reasons: (a) sRGB's transfer function is non-linear, so averaging
        sRGB values is not equivalent to averaging the underlying light and
        converting once; (b) most monochromatic spectral colors lie outside
        the sRGB gamut and need a negative channel value to be represented
        faithfully — clipping that to 0 *before* mixing destroys saturation
        (e.g. a clean blue peak loses its blueness before it even gets
        blended with the rest of the spectrum). Together this produced
        washed-out, pastel results even for spectra with a strong, fairly
        narrow blue peak. Integrating in XYZ first and clipping only once at
        the end (the same approach already used in _spectrum_to_srgb) fixes
        this.

        Factored out of get_far_field_colored so it can also be reused by
        combine_incoherent_colored.
        """
        cmfs = colour.MSDS_CMFS["CIE 1931 2 Degree Standard Observer"]
        x_bar = np.interp(wavelengths_nm, cmfs.wavelengths, cmfs.values[:, 0])
        y_bar = np.interp(wavelengths_nm, cmfs.wavelengths, cmfs.values[:, 1])
        z_bar = np.interp(wavelengths_nm, cmfs.wavelengths, cmfs.values[:, 2])
        cmf_mat = np.column_stack([x_bar, y_bar, z_bar])  # (N_wl, 3)

        # 1) Spectral integration in linear XYZ (no sRGB conversion yet).
        XYZ_per_pixel = np.tensordot(E2_cube, cmf_mat, axes=([2], [0]))  # (na, nb, 3)

        # 2) Pure hue: normalize each pixel's own Y to 1, decoupling
        #    chromaticity from total brightness (mirrors the old 'rgb_flat'
        #    role, but computed in the correct, linear space).
        Y = XYZ_per_pixel[..., 1]
        Y_safe = np.where(Y > 0, Y, 1.0)
        XYZ_hue = XYZ_per_pixel / Y_safe[..., np.newaxis]

        # 3) Convert to sRGB and clip ONCE, after integration.
        rgb_flat = np.clip(colour.XYZ_to_sRGB(XYZ_hue), 0.0, 1.0)

        # 4) Gamma-compressed total-power brightness so weak diffraction
        #    orders remain visible next to the dominant specular peak.
        e2_total = E2_cube.sum(axis=2)  # (na, nb)
        b_max = float(e2_total.max()) or 1.0
        b_norm = e2_total / b_max
        gamma = 0.30
        threshold = 1e-4  # noise floor (0.01 % of peak → black)
        brightness_disp = np.where(b_norm > threshold, b_norm ** gamma, 0.0)

        return np.clip(rgb_flat * brightness_disp[:, :, np.newaxis], 0.0, 1.0)

    @staticmethod
    def combine_incoherent_colored(ff_col_1, ff_col_2):
        """
        Physically correct unpolarized COLOURED far field: incoherently sum
        the E2 cubes of two independent get_far_field_colored() runs (one per
        orthogonal source polarization, e.g. 'TE' and 'TM'), then recolorize.

        Both inputs must share the same (ux, uy) grid and the same wavelength
        sampling (i.e. same na, nb, wl_start, wl_stop, wl_step passed to both
        get_far_field_colored calls).

        Returns: dict with the same keys as get_far_field_colored's output.
        """
        ux1, uy1 = ff_col_1["ux"], ff_col_1["uy"]
        ux2, uy2 = ff_col_2["ux"], ff_col_2["uy"]
        if ux1.shape != ux2.shape or not np.allclose(ux1, ux2) or not np.allclose(uy1, uy2):
            raise ValueError(
                "combine_incoherent_colored requires both colour far fields to "
                "share the same (ux, uy) grid — use the same na/nb in both "
                "get_far_field_colored calls."
            )
        wl1, wl2 = ff_col_1["wavelengths"], ff_col_2["wavelengths"]
        if wl1.shape != wl2.shape or not np.allclose(wl1, wl2):
            raise ValueError(
                "combine_incoherent_colored requires both colour far fields to "
                "share the same wavelength sampling — use the same wl_start/"
                "wl_stop/wl_step in both get_far_field_colored calls."
            )

        E2_cube_sum = ff_col_1["E2_cube"] + ff_col_2["E2_cube"]
        rgb = LumericalSimulation._colorize_E2_cube(E2_cube_sum, wl1)

        return {
            "rgb": rgb,
            "E2_cube": E2_cube_sum,
            "ux": ux1,
            "uy": uy1,
            "wavelengths": wl1,
        }

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