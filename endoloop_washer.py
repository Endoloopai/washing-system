# Cross-platform GPIO handling
try:
    import RPi.GPIO as GPIO
    # We're on a Raspberry Pi
    IS_RASPBERRY_PI = True
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    # We're on a PC/laptop - create a mock GPIO class
    IS_RASPBERRY_PI = False
    
    class MockGPIO:
        OUT = 0
        IN = 1
        HIGH = 1
        LOW = 0
        BCM = 0
        BOARD = 1
        PUD_DOWN = 2  # Add the missing PUD_DOWN constant
        PUD_UP = 3    # Add PUD_UP for completeness
        
        @staticmethod
        def setmode(mode):
            print(f"Mock GPIO: Set mode to {mode}")
            
        @staticmethod
        def setwarnings(flag):
            print(f"Mock GPIO: Set warnings to {flag}")
            
        @staticmethod
        def setup(pin, mode, pull_up_down=None):
            pull_up_str = f", pull_up_down={pull_up_down}" if pull_up_down is not None else ""
            print(f"Mock GPIO: Setup pin {pin} as {'INPUT' if mode == MockGPIO.IN else 'OUTPUT'}{pull_up_str}")
            
        @staticmethod
        def output(pin, value):
            state = "HIGH" if value == MockGPIO.HIGH else "LOW"
            print(f"Mock GPIO: Set pin {pin} to {state}")
            
        @staticmethod
        def input(pin):
            # Simulate water level sensor randomly for testing
            import random
            result = random.choice([True, False])
            print(f"Mock GPIO: Reading from pin {pin}, returning {result}")
            return result
            
        @staticmethod
        def cleanup():
            print("Mock GPIO: Cleaning up")
    
    # Use the mock GPIO
    GPIO = MockGPIO

import platform
import subprocess

# Untuk Windows
try:
    import win32print
    import win32api
except ImportError:
    win32print = None
    win32api = None

import time
import threading

from tkinter.simpledialog import askstring
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkcalendar import DateEntry  # Tambahkan di bagian imports (pip install tkcalendar)
import os
from datetime import datetime, timedelta

try:
    from PIL import Image, ImageTk
except ImportError:
    raise ImportError("Pillow not installed. Use 'pip install Pillow'")

try:
    import barcode
    from barcode.writer import ImageWriter
    import json
    import re
    import uuid
except ImportError:
    barcode = None

# --- Constants ---
PHASES = ['Detergent Wash', 'Rinsing', 'Disinfecting', 'Final Rinse']
PHASE_PINS = {
    'Detergent Wash': 18,
    'Rinsing': 17,
    'Disinfecting': 27,
    'Final Rinse': 22
}
LED_PINS = {
    'status': 5,
    'error': 6
}
BUZZER_PIN = 13

# Valve dan pump pins
INLET_VALVE_PIN = 23  # Pin untuk inlet valve
DRAIN_VALVE_PIN = 24  # Pin untuk drain valve
WATER_PUMP_PIN = 25   # Pin untuk water pump
WATER_LEVEL_PIN = 26  # Pin untuk sensor water level

# Setup GPIO untuk pin baru
for pin in [INLET_VALVE_PIN, DRAIN_VALVE_PIN, WATER_PUMP_PIN]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)
    

if IS_RASPBERRY_PI:
    # Pull-up/down configurations only available on Raspberry Pi
    GPIO.setup(WATER_LEVEL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
else:
    # On PC, simplified setup without pull_up_down
    GPIO.setup(WATER_LEVEL_PIN, GPIO.IN)

GPIO.setmode(GPIO.BCM)
for pin in list(PHASE_PINS.values()) + list(LED_PINS.values()) + [BUZZER_PIN]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Add these new pin constants at the top of your file with the other constants
DISINFECT_PUMP_PIN = 19      # Pin untuk disinfectant pump (berbeda dari water pump biasa)
DISINFECT_INLET_PIN = 16     # Pin untuk inlet valve disinfectant
DISINFECT_DRAIN_PIN = 20     # Pin untuk drain valve disinfectant

# Setup additional GPIO pins for disinfecting system
for pin in [DISINFECT_PUMP_PIN, DISINFECT_INLET_PIN, DISINFECT_DRAIN_PIN]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

OPERATORS_FILE = "operators.json"
SCOPES_FILE = "scopes.json"
OPERATOR_PREFIX = "OP-"
SCOPE_PREFIX = "SC-"

LOG_DIRECTORY = "logs"
LOG_DATABASE = "wash_history.json"

# Folder konstanta

BARCODE_DIRECTORY = "barcodes"  # Tambahkan ini
OPERATOR_BARCODE_DIR = os.path.join(BARCODE_DIRECTORY, "operators")  # Tambahkan ini
SCOPE_BARCODE_DIR = os.path.join(BARCODE_DIRECTORY, "scopes")  # Tambahkan ini


# --- GUI Application ---
class WasherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Endoscope Washer Controller")
        self.root.geometry("700x600")
        self.root.configure(bg="#121212")

        self.phase_vars = {phase: tk.BooleanVar() for phase in PHASES}
        self.phase_times = {phase: tk.IntVar(value=5) for phase in PHASES}

        self.current_phase = tk.StringVar()
        self.timer_display = tk.StringVar(value="--:--")
        self.history_log = []
        
         # Tambahkan variabel untuk menyimpan ID operator dan scope
        self.operator_id = tk.StringVar(value="")
        self.scope_id = tk.StringVar(value="")
        
        # Tambahkan variabel untuk database
        self.operators_db = self.load_database(OPERATORS_FILE)
        self.scopes_db = self.load_database(SCOPES_FILE)
        
        # Variabel untuk capture barcode
        self.barcode_var = tk.StringVar()
        self.barcode_var.trace_add("write", self.process_barcode_input)
        
        # Flag untuk kontrol process
        self.process_running = False
        self.stop_requested = False

        # Pastikan direktori log ada
        if not os.path.exists(LOG_DIRECTORY):
            os.makedirs(LOG_DIRECTORY)

        self.ensure_directories()
        
        # Load history database
        self.history_database = self.load_history_database()

        self.create_widgets()

    def ensure_directories(self):
        """Memastikan semua direktori yang diperlukan sudah ada"""
        directories = [LOG_DIRECTORY, BARCODE_DIRECTORY, OPERATOR_BARCODE_DIR, SCOPE_BARCODE_DIR]
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)

    def create_widgets(self):
        top_frame = tk.Frame(self.root, bg="#1f1f1f")
        top_frame.pack(fill="x")
        tk.Label(top_frame, text="Endoscope Washer", font=("Helvetica", 22, "bold"), bg="#1f1f1f", fg="white").pack(pady=10)

        # Entry untuk barcode scanning - hidden but functional
        barcode_entry = tk.Entry(self.root, textvariable=self.barcode_var)
        barcode_entry.pack()
        barcode_entry.bind("<Return>", lambda e: self.process_barcode_after_enter())
        barcode_entry.focus_set()
        
        # Hidden entry trick - make it 1px but still functional
        barcode_entry.config(width=1, bg="#121212", fg="#121212", highlightthickness=0, bd=0)

        # Input frame untuk Operator dan Scope ID
        input_frame = tk.Frame(self.root, bg="#121212")
        input_frame.pack(pady=5, fill="x", padx=10)
        
        reg_frame = tk.Frame(input_frame, bg="#121212")
        reg_frame.grid(row=0, column=3, rowspan=2, padx=10)
        
        tk.Label(input_frame, text="Operator ID:", bg="#121212", fg="white").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        tk.Entry(input_frame, textvariable=self.operator_id, width=20).grid(row=0, column=1, sticky='w', padx=5)
        
        tk.Label(input_frame, text="Scope ID:", bg="#121212", fg="white").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        tk.Entry(input_frame, textvariable=self.scope_id, width=20).grid(row=1, column=1, sticky='w', padx=5)
        
        tk.Label(reg_frame, text="Registration:", bg="#121212", fg="white").pack(anchor="w")
        reg_buttons = tk.Frame(reg_frame, bg="#121212")
        reg_buttons.pack()
        
        ttk.Button(reg_buttons, text="Register Operator", command=self.register_operator).pack(side=tk.LEFT, padx=2)
        ttk.Button(reg_buttons, text="Register Scope", command=self.register_scope).pack(side=tk.LEFT, padx=2)

        # Scanning instructions
        scan_frame = tk.Frame(self.root, bg="#121212")
        scan_frame.pack(fill="x", padx=10)
        tk.Label(scan_frame, text="Scan barcode untuk operator atau scope untuk mengisi form secara otomatis", 
                bg="#121212", fg="#aaaaaa", font=("Helvetica", 9, "italic")).pack(pady=2)

        config_frame = tk.Frame(self.root, bg="#121212")
        config_frame.pack(pady=10)
        for i, phase in enumerate(PHASES):
            cb = tk.Checkbutton(config_frame, text=phase, variable=self.phase_vars[phase], bg="#121212", fg="white", selectcolor="#333")
            cb.grid(row=i, column=0, sticky='w', padx=5, pady=2)
            spin = tk.Spinbox(config_frame, from_=5, to=60, increment=5, textvariable=self.phase_times[phase], width=5)
            spin.grid(row=i, column=1)
            tk.Label(config_frame, text="menit", bg="#121212", fg="white").grid(row=i, column=2)

        button_frame = tk.Frame(self.root, bg="#121212")
        button_frame.pack(pady=10)
        self.start_button = ttk.Button(button_frame, text="Start Process", command=self.start_process)
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop Process", command=self.stop_process, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=5)
        
        ttk.Button(button_frame, text="View History", command=self.view_history).grid(row=0, column=2, padx=5)
    

        status_frame = tk.Frame(self.root, bg="#121212")
        status_frame.pack(pady=20)
        tk.Label(status_frame, textvariable=self.current_phase, font=("Helvetica", 16), bg="#121212", fg="cyan").pack()
        tk.Label(status_frame, textvariable=self.timer_display, font=("Helvetica", 40, "bold"), fg="lime", bg="#121212").pack()


    def start_process(self):
        # Validasi input operator dan scope
        if not self.operator_id.get():
            messagebox.showerror("Error", "Operator ID harus diisi!")
            return
        
        if not self.scope_id.get():
            messagebox.showerror("Error", "Scope ID harus diisi!")
            return
            
        # Validasi setidaknya 1 fase dipilih
        if not any(self.phase_vars[phase].get() for phase in PHASES):
            messagebox.showerror("Error", "Pilih minimal satu fase untuk dijalankan!")
            return
            
        self.process_running = True
        self.stop_requested = False
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        threading.Thread(target=self.run_all_phases, daemon=True).start()

    def stop_process(self):
        if not self.process_running:
            return
            
        # Konfirmasi apakah pengguna yakin ingin menghentikan proses
        confirm = messagebox.askyesno("Konfirmasi", "Yakin menghentikan proses?")
        if confirm:
            self.stop_requested = True
            self.current_phase.set("Menghentikan Proses...")

    def run_all_phases(self):
        success = True
        GPIO.output(LED_PINS['status'], GPIO.HIGH)
        
        # Mulai mencatat waktu proses dimulai
        start_time = datetime.now()
        log_entry = {
            "timestamp_start": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "operator_id": self.operator_id.get(),
            "scope_id": self.scope_id.get(),
            "phases": [],
            "status": "SUCCESS"
        }
        
        for phase in PHASES:
            if self.stop_requested:
                log_entry["status"] = "STOPPED_BY_USER"
                break
                    
            if self.phase_vars[phase].get():
                duration = self.phase_times[phase].get()
                
                # Jalankan fase yang sesuai
                if phase == 'Detergent Wash':
                    phase_result = self.run_detergent_wash_phase(duration)
                elif phase == 'Rinsing':
                    phase_result = self.run_rinsing_phase(duration)
                elif phase == 'Disinfecting':
                    phase_result = self.run_disinfecting_phase(duration)
                elif phase == 'Final Rinse':
                    phase_result = self.run_final_rinse_phase(duration)
                
                phase_log = {
                    "name": phase,
                    "duration": duration,
                    "status": "SUCCESS" if phase_result else "ERROR"
                }
                log_entry["phases"].append(phase_log)
                
                if not phase_result:
                    success = False
                    log_entry["status"] = "ERROR"
                    break
        
        # Catat waktu proses selesai
        end_time = datetime.now()
        log_entry["timestamp_end"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry["total_duration"] = str(end_time - start_time)
        
        self.history_log.append(log_entry)
        
        # Save log otomatis ke file
        self.save_log_entry(log_entry)
        
        # Update status akhir
        if self.stop_requested:
            self.current_phase.set("Proses dihentikan oleh pengguna")
        else:
            self.current_phase.set("Completed" if success else "ERROR Detected!")
            
        self.timer_display.set("--:--")
        GPIO.output(LED_PINS['status'], GPIO.LOW)
        
        if not success and not self.stop_requested:
            GPIO.output(LED_PINS['error'], GPIO.HIGH)
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.5)
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
        
        # Setelah proses selesai, tampilkan opsi untuk print report
        self.root.after(500, lambda: self.print_wash_report(log_entry))
        
        # Reset button state
        self.process_running = False
        self.stop_requested = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def run_detergent_wash_phase(self, duration_minutes):
        """
        Menjalankan fase Detergent Wash dengan proses yang dimodifikasi:
        1. Membuka inlet valve, menutup drain valve, menyalakan water pump
        2. Menunggu sampai water level tercapai atau batas waktu 1 menit
        3. Menutup inlet valve, mematikan water pump
        4. Menampilkan pesan untuk menambahkan deterjen
        5. Menjalankan timer selama durasi yang ditentukan
        6. Membuka drain valve untuk mengosongkan bak
        """
        phase = 'Detergent Wash'
        pin = PHASE_PINS[phase]
        self.current_phase.set(f"Running: {phase} - Filling Water")
        
        # Indikator fase aktif
        GPIO.output(pin, GPIO.HIGH)
        
        # Step 1: Membuka inlet valve, menutup drain valve, menyalakan water pump
        GPIO.output(INLET_VALVE_PIN, GPIO.HIGH)  # Buka inlet valve
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)   # Tutup drain valve
        GPIO.output(WATER_PUMP_PIN, GPIO.HIGH)   # Nyalakan water pump
        
        # Step 2: Menunggu sampai water level tercapai atau batas waktu 1 menit (60 detik)
        fill_time = 60  # 60 detik untuk pengisian
        fill_start = time.time()
        
        self.timer_display.set("FILL")
        self.root.update()
        
        # Loop selama air belum penuh dan waktu belum habis
        while not GPIO.input(WATER_LEVEL_PIN) and time.time() - fill_start < fill_time:
            # Cek apakah proses dihentikan
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengisian tersisa
            remaining = int(fill_time - (time.time() - fill_start))
            self.timer_display.set(f"F {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Step 3: Menutup inlet valve, mematikan water pump setelah level air tercapai atau waktu habis
        GPIO.output(INLET_VALVE_PIN, GPIO.LOW)  # Tutup inlet valve
        GPIO.output(WATER_PUMP_PIN, GPIO.LOW)   # Matikan water pump
        
        # Step 4: Tampilkan pesan ke operator untuk menambahkan deterjen
        self.current_phase.set(f"Running: {phase} - Water Full")
        messagebox.showinfo("Detergent Wash", "Water level reached. Please add detergent manually and click OK to continue.")
        
        # Step 5: Jalankan timer selama durasi yang ditentukan
        self.current_phase.set(f"Running: {phase} - Washing")
        total_seconds = duration_minutes * 60
        
        for remaining in range(total_seconds, 0, -1):
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                    
            mins, secs = divmod(remaining, 60)
            self.timer_display.set(f"{mins:02d}:{secs:02d}")
            self.root.update()
            time.sleep(1)
        
        # Step 6: Membuka drain valve untuk mengosongkan bak
        self.current_phase.set(f"Running: {phase} - Draining")
        self.timer_display.set("DRAIN")
        self.root.update()
        
        GPIO.output(DRAIN_VALVE_PIN, GPIO.HIGH)  # Buka drain valve
        
        # Tunggu selama waktu pengosongan (1 menit)
        drain_time = 60  # 60 detik untuk pengosongan
        drain_start = time.time()
        
        while time.time() - drain_start < drain_time:
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                    
            # Update timer display dengan waktu pengosongan tersisa
            remaining = int(drain_time - (time.time() - drain_start))
            self.timer_display.set(f"D {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Fase Detergent Wash selesai
        self.shutdown_all_valves()
        GPIO.output(pin, GPIO.LOW)
        self.timer_display.set("00:00")
        return True
    
    def run_rinsing_phase(self, duration_minutes):
        """
        Menjalankan fase Rinsing dengan proses yang dimodifikasi:
        1. Membuka inlet valve, menutup drain valve, menyalakan water pump
        2. Menunggu sampai water level tercapai atau batas waktu 1 menit
        3. Menutup inlet valve, mematikan water pump
        4. Menjalankan timer selama durasi yang ditentukan
        5. Membuka drain valve untuk mengosongkan bak
        """
        phase = 'Rinsing'
        pin = PHASE_PINS[phase]
        self.current_phase.set(f"Running: {phase} - Filling Water")
        
        # Indikator fase aktif
        GPIO.output(pin, GPIO.HIGH)
        
        # Step 1: Membuka inlet valve, menutup drain valve, menyalakan water pump
        GPIO.output(INLET_VALVE_PIN, GPIO.HIGH)  # Buka inlet valve
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)   # Tutup drain valve
        GPIO.output(WATER_PUMP_PIN, GPIO.HIGH)   # Nyalakan water pump
        
        # Step 2: Menunggu sampai water level tercapai atau batas waktu 1 menit (60 detik)
        fill_time = 60  # 60 detik untuk pengisian
        fill_start = time.time()
        
        self.timer_display.set("FILL")
        self.root.update()
        
        # Loop selama air belum penuh dan waktu belum habis
        while not GPIO.input(WATER_LEVEL_PIN) and time.time() - fill_start < fill_time:
            # Cek apakah proses dihentikan
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengisian tersisa
            remaining = int(fill_time - (time.time() - fill_start))
            self.timer_display.set(f"F {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Step 3: Menutup inlet valve, mematikan water pump setelah level air tercapai atau waktu habis
        GPIO.output(INLET_VALVE_PIN, GPIO.LOW)  # Tutup inlet valve
        GPIO.output(WATER_PUMP_PIN, GPIO.LOW)   # Matikan water pump
        
        # Step 4: Jalankan timer selama durasi yang ditentukan
        self.current_phase.set(f"Running: {phase} - Rinsing")
        total_seconds = duration_minutes * 60
        
        for remaining in range(total_seconds, 0, -1):
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            mins, secs = divmod(remaining, 60)
            self.timer_display.set(f"{mins:02d}:{secs:02d}")
            self.root.update()
            time.sleep(1)
        
        # Step 5: Membuka drain valve untuk mengosongkan bak
        self.current_phase.set(f"Running: {phase} - Draining")
        self.timer_display.set("DRAIN")
        self.root.update()
        
        GPIO.output(DRAIN_VALVE_PIN, GPIO.HIGH)  # Buka drain valve
        
        # Tunggu selama waktu pengosongan (1 menit)
        drain_time = 60  # 60 detik untuk pengosongan
        drain_start = time.time()
        
        while time.time() - drain_start < drain_time:
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengosongan tersisa
            remaining = int(drain_time - (time.time() - drain_start))
            self.timer_display.set(f"D {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Fase Rinsing selesai
        self.shutdown_all_valves()
        GPIO.output(pin, GPIO.LOW)
        self.timer_display.set("00:00")
        return True
    
    def run_disinfecting_phase(self, duration_minutes):
        """
        Menjalankan fase Disinfecting dengan proses khusus:
        1. Membuka inlet valve disinfectant, menutup semua drain valve, menyalakan disinfectant pump
        2. Menunggu sampai water level tercapai atau batas waktu 1 menit
        3. Menutup inlet valve disinfectant, mematikan disinfectant pump
        4. Menjalankan timer selama durasi yang ditentukan
        5. Membuka drain valve disinfectant untuk mengembalikan cairan ke tank disinfectant
        (drain valve utama tetap tertutup)
        """
        phase = 'Disinfecting'
        pin = PHASE_PINS[phase]
        self.current_phase.set(f"Running: {phase} - Filling Disinfectant")
        
        # Indikator fase aktif
        GPIO.output(pin, GPIO.HIGH)
        
        # Step 1: Membuka inlet valve disinfectant, menutup semua drain valve, menyalakan disinfectant pump
        GPIO.output(DISINFECT_INLET_PIN, GPIO.HIGH)  # Buka inlet valve disinfectant
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)       # Tutup drain valve utama
        GPIO.output(DISINFECT_DRAIN_PIN, GPIO.LOW)   # Tutup drain valve disinfectant
        GPIO.output(DISINFECT_PUMP_PIN, GPIO.HIGH)   # Nyalakan disinfectant pump
        
        # Step 2: Menunggu sampai water level tercapai atau batas waktu 1 menit (60 detik)
        fill_time = 60  # 60 detik untuk pengisian
        fill_start = time.time()
        
        self.timer_display.set("FILL")
        self.root.update()
        
        # Loop selama level disinfectant belum penuh dan waktu belum habis
        while not GPIO.input(WATER_LEVEL_PIN) and time.time() - fill_start < fill_time:
            # Cek apakah proses dihentikan
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengisian tersisa
            remaining = int(fill_time - (time.time() - fill_start))
            self.timer_display.set(f"F {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Step 3: Menutup inlet valve disinfectant, mematikan disinfectant pump setelah level tercapai
        GPIO.output(DISINFECT_INLET_PIN, GPIO.LOW)   # Tutup inlet valve disinfectant
        GPIO.output(DISINFECT_PUMP_PIN, GPIO.LOW)    # Matikan disinfectant pump
        
        # Step 4: Jalankan timer selama durasi yang ditentukan
        self.current_phase.set(f"Running: {phase} - Disinfecting")
        total_seconds = duration_minutes * 60
        
        for remaining in range(total_seconds, 0, -1):
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            mins, secs = divmod(remaining, 60)
            self.timer_display.set(f"{mins:02d}:{secs:02d}")
            self.root.update()
            time.sleep(1)
        
        # Step 5: Membuka drain valve disinfectant untuk mengembalikan cairan ke tank disinfectant
        self.current_phase.set(f"Running: {phase} - Returning Disinfectant")
        self.timer_display.set("DRAIN")
        self.root.update()
        
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)       # Pastikan drain valve utama tetap tertutup
        GPIO.output(DISINFECT_DRAIN_PIN, GPIO.HIGH)  # Buka drain valve disinfectant
        GPIO.output(DISINFECT_PUMP_PIN, GPIO.HIGH)   # Nyalakan kembali pump untuk membantu proses drain
        
        # Tunggu selama waktu pengosongan (1 menit)
        drain_time = 60  # 60 detik untuk pengembalian cairan disinfectant
        drain_start = time.time()
        
        while time.time() - drain_start < drain_time:
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengosongan tersisa
            remaining = int(drain_time - (time.time() - drain_start))
            self.timer_display.set(f"D {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Fase Disinfecting selesai
        self.shutdown_all_valves()
        GPIO.output(pin, GPIO.LOW)
        self.timer_display.set("00:00")
        return True

    

    def run_final_rinse_phase(self, duration_minutes):
        """
        Menjalankan fase Final Rinse dengan proses yang dimodifikasi:
        1. Membuka inlet valve, menutup drain valve, menyalakan water pump
        2. Menunggu sampai water level tercapai atau batas waktu 1 menit
        3. Menutup inlet valve, mematikan water pump
        4. Menjalankan timer selama durasi yang ditentukan
        5. Membuka drain valve untuk mengosongkan bak
        """
        phase = 'Final Rinse'
        pin = PHASE_PINS[phase]
        self.current_phase.set(f"Running: {phase} - Filling Water")
        
        # Indikator fase aktif
        GPIO.output(pin, GPIO.HIGH)
        
        # Step 1: Membuka inlet valve, menutup drain valve, menyalakan water pump
        GPIO.output(INLET_VALVE_PIN, GPIO.HIGH)  # Buka inlet valve
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)   # Tutup drain valve
        GPIO.output(WATER_PUMP_PIN, GPIO.HIGH)   # Nyalakan water pump
        
        # Step 2: Menunggu sampai water level tercapai atau batas waktu 1 menit (60 detik)
        fill_time = 60  # 60 detik untuk pengisian
        fill_start = time.time()
        
        self.timer_display.set("FILL")
        self.root.update()
        
        # Loop selama air belum penuh dan waktu belum habis
        while not GPIO.input(WATER_LEVEL_PIN) and time.time() - fill_start < fill_time:
            # Cek apakah proses dihentikan
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengisian tersisa
            remaining = int(fill_time - (time.time() - fill_start))
            self.timer_display.set(f"F {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Step 3: Menutup inlet valve, water pump tetap menyala selama proses final rinse
        GPIO.output(INLET_VALVE_PIN, GPIO.LOW)  # Tutup inlet valve
        
        # Step 4: Jalankan timer selama durasi yang ditentukan (water pump tetap aktif untuk sirkulasi)
        self.current_phase.set(f"Running: {phase} - Final Rinsing")
        total_seconds = duration_minutes * 60
        
        for remaining in range(total_seconds, 0, -1):
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            mins, secs = divmod(remaining, 60)
            self.timer_display.set(f"{mins:02d}:{secs:02d}")
            self.root.update()
            time.sleep(1)
        
        # Step 5: Membuka drain valve untuk mengosongkan bak
        self.current_phase.set(f"Running: {phase} - Draining")
        self.timer_display.set("DRAIN")
        self.root.update()
        
        GPIO.output(WATER_PUMP_PIN, GPIO.LOW)     # Matikan water pump
        GPIO.output(DRAIN_VALVE_PIN, GPIO.HIGH)   # Buka drain valve
        
        # Tunggu selama waktu pengosongan (1 menit)
        drain_time = 60  # 60 detik untuk pengosongan
        drain_start = time.time()
        
        while time.time() - drain_start < drain_time:
            if self.stop_requested:
                self.shutdown_all_valves()
                GPIO.output(pin, GPIO.LOW)
                return False
                
            # Update timer display dengan waktu pengosongan tersisa
            remaining = int(drain_time - (time.time() - drain_start))
            self.timer_display.set(f"D {remaining:02d}s")
            self.root.update()
            time.sleep(0.5)
        
        # Final Rinse selesai
        self.shutdown_all_valves()
        GPIO.output(pin, GPIO.LOW)
        self.timer_display.set("00:00")
        return True

    def shutdown_all_valves(self):
        """Mematikan semua valve dan pump untuk keamanan"""
        GPIO.output(INLET_VALVE_PIN, GPIO.LOW)
        GPIO.output(DRAIN_VALVE_PIN, GPIO.LOW)
        GPIO.output(WATER_PUMP_PIN, GPIO.LOW)
        GPIO.output(DISINFECT_INLET_PIN, GPIO.LOW)
        GPIO.output(DISINFECT_DRAIN_PIN, GPIO.LOW)
        GPIO.output(DISINFECT_PUMP_PIN, GPIO.LOW)

    
    def simulate_flow_check(self):
        # Placeholder for sensor simulation — always return True
        return True

    def load_database(self, filename):
        try:
            if os.path.exists(filename):
                with open(filename, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading database {filename}: {e}")
        return {}  # Return empty dictionary instead of empty list

    def save_database(self, data, filename):
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving database {filename}: {e}")
            messagebox.showerror("Database Error", f"Failed to save to {filename}: {e}")
            return False

    def register_operator(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Register New Operator")
        dialog.geometry("400x250")
        dialog.configure(bg="#1f1f1f")
        
        tk.Label(dialog, text="Register New Operator", font=("Helvetica", 14, "bold"), bg="#1f1f1f", fg="white").pack(pady=10)
        
        form_frame = tk.Frame(dialog, bg="#1f1f1f")
        form_frame.pack(pady=5)
        
        name_var = tk.StringVar()
        id_var = tk.StringVar()
        
        tk.Label(form_frame, text="Name:", bg="#1f1f1f", fg="white").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        tk.Entry(form_frame, textvariable=name_var, width=25).grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(form_frame, text="ID (optional):", bg="#1f1f1f", fg="white").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        tk.Entry(form_frame, textvariable=id_var, width=25).grid(row=1, column=1, padx=5, pady=5)
        
        def save_operator():
            name = name_var.get().strip()
            op_id = id_var.get().strip()
            
            if not name:
                messagebox.showerror("Error", "Name is required!")
                return
                
            if not op_id:
                op_id = f"{OPERATOR_PREFIX}{uuid.uuid4().hex[:8].upper()}"
            elif not op_id.startswith(OPERATOR_PREFIX):
                op_id = f"{OPERATOR_PREFIX}{op_id}"
                
            # Check if ID already exists
            if op_id in self.operators_db:
                messagebox.showerror("Error", f"Operator ID {op_id} already exists!")
                return
                
            # Add to database
            self.operators_db[op_id] = {"name": name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            if self.save_database(self.operators_db, OPERATORS_FILE):
                messagebox.showinfo("Success", f"Operator {name} registered with ID: {op_id}")
                # Generate barcode with path to operator folder
                barcode_filename = os.path.join(OPERATOR_BARCODE_DIR, f'operator_{op_id}')
                self.generate_barcode(op_id, barcode_filename, True)
                dialog.destroy()
        
        buttons_frame = tk.Frame(dialog, bg="#1f1f1f")
        buttons_frame.pack(pady=10)
        
        ttk.Button(buttons_frame, text="Save & Generate Barcode", command=save_operator).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        dialog.transient(self.root)
        dialog.grab_set()
        
    def register_scope(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Register New Scope")
        dialog.geometry("400x300")
        dialog.configure(bg="#1f1f1f")
        
        tk.Label(dialog, text="Register New Scope", font=("Helvetica", 14, "bold"), bg="#1f1f1f", fg="white").pack(pady=10)
        
        form_frame = tk.Frame(dialog, bg="#1f1f1f")
        form_frame.pack(pady=5)
        
        model_var = tk.StringVar()
        serial_var = tk.StringVar()
        id_var = tk.StringVar()
        
        tk.Label(form_frame, text="Model:", bg="#1f1f1f", fg="white").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        tk.Entry(form_frame, textvariable=model_var, width=25).grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(form_frame, text="Serial Number:", bg="#1f1f1f", fg="white").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        tk.Entry(form_frame, textvariable=serial_var, width=25).grid(row=1, column=1, padx=5, pady=5)
        
        tk.Label(form_frame, text="ID (optional):", bg="#1f1f1f", fg="white").grid(row=2, column=0, sticky='w', padx=5, pady=5)
        tk.Entry(form_frame, textvariable=id_var, width=25).grid(row=2, column=1, padx=5, pady=5)
        
        def save_scope():
            model = model_var.get().strip()
            serial = serial_var.get().strip()
            scope_id = id_var.get().strip()
            
            if not model or not serial:
                messagebox.showerror("Error", "Model and Serial Number are required!")
                return
                
            if not scope_id:
                scope_id = f"{SCOPE_PREFIX}{uuid.uuid4().hex[:8].upper()}"
            elif not scope_id.startswith(SCOPE_PREFIX):
                scope_id = f"{SCOPE_PREFIX}{scope_id}"
                
            # Check if ID already exists
            if scope_id in self.scopes_db:
                messagebox.showerror("Error", f"Scope ID {scope_id} already exists!")
                return
                
            # Add to database
            self.scopes_db[scope_id] = {
                "model": model,
                "serial": serial,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if self.save_database(self.scopes_db, SCOPES_FILE):
                messagebox.showinfo("Success", f"Scope {model} ({serial}) registered with ID: {scope_id}")
                # Generate barcode with path to scope folder
                barcode_filename = os.path.join(SCOPE_BARCODE_DIR, f'scope_{scope_id}')
                self.generate_barcode(scope_id, barcode_filename, True)
                dialog.destroy()
        
        buttons_frame = tk.Frame(dialog, bg="#1f1f1f")
        buttons_frame.pack(pady=10)
        
        ttk.Button(buttons_frame, text="Save & Generate Barcode", command=save_scope).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        dialog.transient(self.root)
        dialog.grab_set()

    # --- Metode untuk memproses input barcode ---
    def process_barcode_input(self, *args):
        barcode_data = self.barcode_var.get().strip()
        
        # Hanya proses jika panjang barcode cukup
        if len(barcode_data) < 3:
            return
            
        # Reset var setelah diproses
        self.barcode_var.set("")
        
        if barcode_data.startswith(OPERATOR_PREFIX):
            # Ini adalah barcode operator
            if barcode_data in self.operators_db:
                operator_info = self.operators_db[barcode_data]
                self.operator_id.set(barcode_data)
                messagebox.showinfo("Operator Detected", f"Operator: {operator_info['name']}")
            else:
                messagebox.showerror("Error", f"Unknown operator ID: {barcode_data}")
                
        elif barcode_data.startswith(SCOPE_PREFIX):
            # Ini adalah barcode scope
            if barcode_data in self.scopes_db:
                scope_info = self.scopes_db[barcode_data]
                self.scope_id.set(barcode_data)
                messagebox.showinfo("Scope Detected", 
                                f"Scope: {scope_info['model']}\nSerial: {scope_info['serial']}")
            else:
                messagebox.showerror("Error", f"Unknown scope ID: {barcode_data}")
        else:
            messagebox.showwarning("Warning", f"Unrecognized barcode format: {barcode_data}")

    def process_barcode_after_enter(self):
        # Fungsi ini dipicu ketika pengguna menekan Enter setelah memasukkan barcode
        # Ini memberikan waktu untuk membaca barcode secara penuh
        self.root.after(100, lambda: self.process_barcode_input())

    # --- Update metode generate_barcode ---
    def generate_barcode(self, code, filename, show_preview=False):
        if barcode:
            try:
                # Create the directory if it doesn't exist
                directory = os.path.dirname(filename)
                if not os.path.exists(directory):
                    os.makedirs(directory)
                    
                bcode = barcode.get('code128', code, writer=ImageWriter())
                filepath = bcode.save(filename)
                
                if show_preview and os.path.exists(filepath):
                    try:
                        # Open barcode image in new window
                        preview = tk.Toplevel(self.root)
                        preview.title(f"Barcode: {code}")
                        preview.geometry("400x300")
                        
                        # Load image
                        img = Image.open(filepath)
                        img = ImageTk.PhotoImage(img)
                        
                        # Create label and show image
                        panel = tk.Label(preview, image=img)
                        panel.image = img  # Keep reference
                        panel.pack(pady=10)
                        
                        tk.Label(preview, text=f"ID: {code}", font=("Helvetica", 12)).pack(pady=5)
                        
                        if code.startswith(OPERATOR_PREFIX) and code in self.operators_db:
                            tk.Label(preview, text=f"Name: {self.operators_db[code]['name']}", 
                                font=("Helvetica", 12)).pack(pady=2)
                        elif code.startswith(SCOPE_PREFIX) and code in self.scopes_db:
                            scope = self.scopes_db[code]
                            tk.Label(preview, text=f"Model: {scope['model']}", font=("Helvetica", 12)).pack(pady=2)
                            tk.Label(preview, text=f"Serial: {scope['serial']}", font=("Helvetica", 12)).pack(pady=2)
                        
                        # Tambahkan informasi path file
                        tk.Label(preview, text=f"File path: {filepath}", font=("Helvetica", 8), fg="gray").pack(pady=2)
                            
                        ttk.Button(preview, text="Print", command=lambda: self.print_barcode(filepath)).pack(pady=10)
                        ttk.Button(preview, text="Close", command=preview.destroy).pack(pady=5)
                    except Exception as e:
                        messagebox.showerror("Preview Error", f"Failed to preview barcode: {str(e)}")
                
                return True, filepath
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create barcode: {str(e)}")
                return False, None
        else:
            messagebox.showwarning("Warning", "Barcode module not installed.")
            return False, None

    def print_barcode(self, filepath):
        # Fungsi ini sebagai placeholder untuk fungsionalitas print
        # Di implementasi nyata, bisa menggunakan library seperti win32print untuk Windows
        messagebox.showinfo("Print", f"Printing barcode: {filepath}\n\nPlease implement actual printing functionality using appropriate library for your system.")

    def force_scan(self):
        """Buka dialog untuk memasukkan kode barcode secara manual"""
        code = askstring("Manual Barcode Input", "Enter barcode or ID code:")
        if code:
            self.barcode_var.set(code)
            self.process_barcode_input()

    def load_history_database(self):
        """Load history database dari file JSON"""
        history_path = os.path.join(LOG_DIRECTORY, LOG_DATABASE)
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading history database: {e}")
        return []

    def save_history_database(self):
        """Save history database ke file JSON"""
        history_path = os.path.join(LOG_DIRECTORY, LOG_DATABASE)
        try:
            with open(history_path, 'w') as f:
                json.dump(self.history_database, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving history database: {e}")
            return False

    def save_log_entry(self, log_entry):
        """Save single log entry ke database dan file text"""
        # Tambahkan ke database history
        self.history_database.append(log_entry)
        self.save_history_database()
        
        # Simpan juga ke file text untuk mudah dibaca
        timestamp = datetime.strptime(log_entry['timestamp_start'], "%Y-%m-%d %H:%M:%S")
        log_filename = f"{LOG_DIRECTORY}/washer_log_{timestamp.strftime('%Y%m%d_%H%M%S')}_{log_entry['scope_id']}.txt"
        
        try:
            with open(log_filename, "w") as f:
                f.write("=============== ENDOSCOPE WASHER LOG ===============\n")
                f.write(f"Tanggal: {log_entry['timestamp_start']}\n")
                f.write(f"Operator ID: {log_entry['operator_id']}\n")
                
                # Tambahkan nama operator jika tersedia
                if log_entry['operator_id'] in self.operators_db:
                    f.write(f"Operator Name: {self.operators_db[log_entry['operator_id']]['name']}\n")
                    
                f.write(f"Scope ID: {log_entry['scope_id']}\n")
                
                # Tambahkan info scope jika tersedia
                if log_entry['scope_id'] in self.scopes_db:
                    scope_info = self.scopes_db[log_entry['scope_id']]
                    f.write(f"Scope Model: {scope_info['model']}\n")
                    f.write(f"Scope Serial: {scope_info['serial']}\n")
                    
                f.write(f"Waktu Mulai: {log_entry['timestamp_start']}\n")
                f.write(f"Waktu Selesai: {log_entry['timestamp_end']}\n")
                f.write(f"Total Durasi: {log_entry['total_duration']}\n")
                f.write(f"Status: {log_entry['status']}\n")
                f.write("Detail Fase:\n")
                
                for phase in log_entry['phases']:
                    f.write(f"  - {phase['name']}: {phase['status']} ({phase['duration']} menit)\n")
                
                f.write("="*50 + "\n\n")
            
            print(f"Log saved to {log_filename}")
            return True
        except Exception as e:
            print(f"Error saving log: {e}")
            messagebox.showerror("Error", f"Gagal menyimpan log: {str(e)}")
            return False

    def view_history(self):
        """Tampilkan dialog history"""
        history_dialog = tk.Toplevel(self.root)
        history_dialog.title("Wash History")
        history_dialog.geometry("800x600")
        history_dialog.configure(bg="#1f1f1f")
        
        # Frame untuk filter
        filter_frame = tk.Frame(history_dialog, bg="#1f1f1f")
        filter_frame.pack(fill="x", padx=10, pady=10)
        
        # Date filter
        tk.Label(filter_frame, text="From Date:", bg="#1f1f1f", fg="white").grid(row=0, column=0, padx=5, pady=5)
        from_date = DateEntry(filter_frame, width=12, background='darkblue', foreground='white', date_pattern='yyyy-mm-dd')
        from_date.grid(row=0, column=1, padx=5, pady=5)
        # Set default from date (7 days ago)
        from_date.set_date((datetime.now() - timedelta(days=7)).date())
        
        tk.Label(filter_frame, text="To Date:", bg="#1f1f1f", fg="white").grid(row=0, column=2, padx=5, pady=5)
        to_date = DateEntry(filter_frame, width=12, background='darkblue', foreground='white', date_pattern='yyyy-mm-dd')
        to_date.grid(row=0, column=3, padx=5, pady=5)
        
        # Scope ID filter
        tk.Label(filter_frame, text="Scope ID:", bg="#1f1f1f", fg="white").grid(row=0, column=4, padx=5, pady=5)
        scope_id_var = tk.StringVar()
        scope_combo = ttk.Combobox(filter_frame, textvariable=scope_id_var, width=15)
        scope_combo.grid(row=0, column=5, padx=5, pady=5)
        
        # Populate scope dropdown with unique scope IDs from history
        scope_ids = set()
        for entry in self.history_database:
            if 'scope_id' in entry:
                scope_ids.add(entry['scope_id'])
        scope_combo['values'] = [''] + list(scope_ids)  # Empty option + all scopes
        
        # Results tree view
        results_frame = tk.Frame(history_dialog, bg="#1f1f1f")
        results_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        columns = ('date', 'scope_id', 'operator_id', 'status', 'duration')
        tree = ttk.Treeview(results_frame, columns=columns, show='headings')
        
        # Configure columns
        tree.heading('date', text='Date/Time')
        tree.heading('scope_id', text='Scope ID')
        tree.heading('operator_id', text='Operator')
        tree.heading('status', text='Status')
        tree.heading('duration', text='Duration')
        
        tree.column('date', width=150)
        tree.column('scope_id', width=100)
        tree.column('operator_id', width=100)
        tree.column('status', width=100)
        tree.column('duration', width=100)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        tree.pack(fill="both", expand=True)
        
        # Details frame
        details_frame = tk.Frame(history_dialog, bg="#1f1f1f", height=200)
        details_frame.pack(fill="x", padx=10, pady=5)
        
        details_text = tk.Text(details_frame, height=10, bg="#2a2a2a", fg="white")
        details_text.pack(fill="x", pady=5)
        
        # Populate tree view function
        def populate_tree():
            # Clear existing entries
            for item in tree.get_children():
                tree.delete(item)
                
            # Get filter values
            from_date_str = from_date.get_date().strftime("%Y-%m-%d")
            to_date_str = to_date.get_date().strftime("%Y-%m-%d")
            # Add time to make it end of day
            to_date_str += " 23:59:59"
            scope_filter = scope_id_var.get()
            
            # Filter and add entries
            count = 0
            for entry in self.history_database:
                # Check date filter
                if 'timestamp_start' not in entry:
                    continue
                    
                entry_date = entry['timestamp_start']
                
                if entry_date < from_date_str or entry_date > to_date_str:
                    continue
                    
                # Check scope filter
                if scope_filter and entry.get('scope_id', '') != scope_filter:
                    continue
                    
                # Add to tree
                tree.insert('', 'end', values=(
                    entry['timestamp_start'],
                    entry.get('scope_id', 'N/A'),
                    entry.get('operator_id', 'N/A'),
                    entry.get('status', 'N/A'),
                    entry.get('total_duration', 'N/A')
                ), tags=(entry.get('status', '')))
                count += 1
                
            status_label.config(text=f"{count} records found")
        
        # Event handler for tree selection
        def show_details(event):
            selected_item = tree.selection()
            if not selected_item:
                return
                
            item_index = tree.index(selected_item[0])
            if item_index >= len(self.history_database):
                return
                
            # Get the log entry
            entry = None
            count = 0
            for e in self.history_database:
                # Apply same filters as in populate_tree
                from_date_str = from_date.get_date().strftime("%Y-%m-%d")
                to_date_str = to_date.get_date().strftime("%Y-%m-%d") + " 23:59:59"
                scope_filter = scope_id_var.get()
                
                if 'timestamp_start' not in e:
                    continue
                    
                entry_date = e['timestamp_start']
                
                if entry_date < from_date_str or entry_date > to_date_str:
                    continue
                    
                if scope_filter and e.get('scope_id', '') != scope_filter:
                    continue
                    
                if count == item_index:
                    entry = e
                    break
                count += 1
            
            if not entry:
                return
                
            # Clear details
            details_text.delete(1.0, tk.END)
            
            # Format details
            details = f"Date: {entry.get('timestamp_start', 'N/A')}\n"
            details += f"Operator ID: {entry.get('operator_id', 'N/A')}\n"
            
            # Add operator name if available
            op_id = entry.get('operator_id', '')
            if op_id in self.operators_db:
                details += f"Operator Name: {self.operators_db[op_id]['name']}\n"
                
            details += f"Scope ID: {entry.get('scope_id', 'N/A')}\n"
            
            # Add scope details if available
            scope_id = entry.get('scope_id', '')
            if scope_id in self.scopes_db:
                scope = self.scopes_db[scope_id]
                details += f"Scope Model: {scope.get('model', 'N/A')}\n"
                details += f"Scope Serial: {scope.get('serial', 'N/A')}\n"
                
            details += f"Status: {entry.get('status', 'N/A')}\n"
            details += f"Duration: {entry.get('total_duration', 'N/A')}\n\n"
            
            details += "Phases:\n"
            for phase in entry.get('phases', []):
                details += f"  - {phase.get('name', 'N/A')}: {phase.get('status', 'N/A')} ({phase.get('duration', 0)} min)\n"
                
            details_text.insert(tk.END, details)
            
        # Bind selection event
        tree.bind('<<TreeviewSelect>>', show_details)
        
        # Filter button
        filter_button = ttk.Button(filter_frame, text="Apply Filter", command=populate_tree)
        filter_button.grid(row=0, column=6, padx=10)
        
        # Export button
        def export_logs():
            # Ask for directory
            export_dir = filedialog.askdirectory(title="Select Export Directory")
            if not export_dir:
                return
                
            # Export filtered logs
            exported = 0
            from_date_str = from_date.get_date().strftime("%Y-%m-%d")
            to_date_str = to_date.get_date().strftime("%Y-%m-%d") + " 23:59:59"
            scope_filter = scope_id_var.get()
            
            for entry in self.history_database:
                # Apply same filters as in populate_tree
                if 'timestamp_start' not in entry:
                    continue
                    
                entry_date = entry['timestamp_start']
                
                if entry_date < from_date_str or entry_date > to_date_str:
                    continue
                    
                if scope_filter and entry.get('scope_id', '') != scope_filter:
                    continue
                    
                # Save this log
                timestamp = datetime.strptime(entry['timestamp_start'], "%Y-%m-%d %H:%M:%S")
                log_filename = os.path.join(export_dir, f"washer_log_{timestamp.strftime('%Y%m%d_%H%M%S')}_{entry.get('scope_id', 'unknown')}.txt")
                
                try:
                    with open(log_filename, "w") as f:
                        f.write("=============== ENDOSCOPE WASHER LOG ===============\n")
                        f.write(f"Tanggal: {entry['timestamp_start']}\n")
                        f.write(f"Operator ID: {entry.get('operator_id', 'N/A')}\n")
                        
                        # Tambahkan nama operator jika tersedia
                        op_id = entry.get('operator_id', '')
                        if op_id in self.operators_db:
                            f.write(f"Operator Name: {self.operators_db[op_id]['name']}\n")
                            
                        f.write(f"Scope ID: {entry.get('scope_id', 'N/A')}\n")
                        
                        # Tambahkan info scope jika tersedia
                        scope_id = entry.get('scope_id', '')
                        if scope_id in self.scopes_db:
                            scope_info = self.scopes_db[scope_id]
                            f.write(f"Scope Model: {scope_info.get('model', 'N/A')}\n")
                            f.write(f"Scope Serial: {scope_info.get('serial', 'N/A')}\n")
                            
                        f.write(f"Waktu Mulai: {entry.get('timestamp_start', 'N/A')}\n")
                        f.write(f"Waktu Selesai: {entry.get('timestamp_end', 'N/A')}\n")
                        f.write(f"Total Durasi: {entry.get('total_duration', 'N/A')}\n")
                        f.write(f"Status: {entry.get('status', 'N/A')}\n")
                        f.write("Detail Fase:\n")
                        
                        for phase in entry.get('phases', []):
                            f.write(f"  - {phase.get('name', 'N/A')}: {phase.get('status', 'N/A')} ({phase.get('duration', 0)} menit)\n")
                        
                        f.write("="*50 + "\n\n")
                    exported += 1
                except Exception as e:
                    print(f"Error exporting log: {e}")
            
            messagebox.showinfo("Export Complete", f"{exported} logs exported to {export_dir}")
        
        export_button = ttk.Button(filter_frame, text="Export Logs", command=export_logs)
        export_button.grid(row=0, column=7, padx=10)

        def print_selected_log():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showinfo("Info", "Pilih log yang ingin dicetak terlebih dahulu")
                return
                
            item_index = tree.index(selected_item[0])
            
            # Cari entry yang sesuai dengan filter dan indeks
            entry = None
            count = 0
            for e in self.history_database:
                # Apply same filters as in populate_tree
                from_date_str = from_date.get_date().strftime("%Y-%m-%d")
                to_date_str = to_date.get_date().strftime("%Y-%m-%d") + " 23:59:59"
                scope_filter = scope_id_var.get()
                
                if 'timestamp_start' not in e:
                    continue
                    
                entry_date = e['timestamp_start']
                
                if entry_date < from_date_str or entry_date > to_date_str:
                    continue
                    
                if scope_filter and e.get('scope_id', '') != scope_filter:
                    continue
                    
                if count == item_index:
                    entry = e
                    break
                count += 1
            
            if not entry:
                messagebox.showinfo("Info", "Log tidak ditemukan")
                return
                
            # Generate temporary log file
            timestamp = datetime.strptime(entry['timestamp_start'], "%Y-%m-%d %H:%M:%S")
            log_filename = os.path.join(LOG_DIRECTORY, f"temp_print_log_{timestamp.strftime('%Y%m%d_%H%M%S')}_{entry.get('scope_id', 'unknown')}.txt")
            
            try:
                with open(log_filename, "w") as f:
                    f.write("=============== ENDOSCOPE WASHER LOG ===============\n")
                    f.write(f"Tanggal: {entry['timestamp_start']}\n")
                    f.write(f"Operator ID: {entry.get('operator_id', 'N/A')}\n")
                    
                    # Tambahkan nama operator jika tersedia
                    op_id = entry.get('operator_id', '')
                    if op_id in self.operators_db:
                        f.write(f"Operator Name: {self.operators_db[op_id]['name']}\n")
                        
                    f.write(f"Scope ID: {entry.get('scope_id', 'N/A')}\n")
                    
                    # Tambahkan info scope jika tersedia
                    scope_id = entry.get('scope_id', '')
                    if scope_id in self.scopes_db:
                        scope_info = self.scopes_db[scope_id]
                        f.write(f"Scope Model: {scope_info.get('model', 'N/A')}\n")
                        f.write(f"Scope Serial: {scope_info.get('serial', 'N/A')}\n")
                        
                    f.write(f"Waktu Mulai: {entry.get('timestamp_start', 'N/A')}\n")
                    f.write(f"Waktu Selesai: {entry.get('timestamp_end', 'N/A')}\n")
                    f.write(f"Total Durasi: {entry.get('total_duration', 'N/A')}\n")
                    f.write(f"Status: {entry.get('status', 'N/A')}\n")
                    f.write("Detail Fase:\n")
                    
                    for phase in entry.get('phases', []):
                        f.write(f"  - {phase.get('name', 'N/A')}: {phase.get('status', 'N/A')} ({phase.get('duration', 0)} menit)\n")
                    
                    f.write("="*50 + "\n\n")
                    
                # Tampilkan print preview dan cetak
                self.print_report(log_filename)
                
                # Hapus file sementara setelah 60 detik
                def delete_temp_file():
                    try:
                        if os.path.exists(log_filename):
                            os.remove(log_filename)
                    except:
                        pass
                
                history_dialog.after(60000, delete_temp_file)
                
            except Exception as e:
                messagebox.showerror("Error", f"Gagal mencetak log: {str(e)}")

        print_button = ttk.Button(filter_frame, text="Print Log", command=print_selected_log)
        print_button.grid(row=0, column=8, padx=10)
        
        # Status bar
        status_frame = tk.Frame(history_dialog, bg="#1f1f1f")
        status_frame.pack(fill="x", padx=10, pady=5)
        
        status_label = tk.Label(status_frame, text="Ready", bg="#1f1f1f", fg="white")
        status_label.pack(side=tk.LEFT)
        
        # Configure tree colors
        style = ttk.Style()
        style.map('Treeview', foreground=[('tag-ERROR', 'red'), ('tag-SUCCESS', 'green'), ('tag-STOPPED_BY_USER', 'orange')])
        
        # Load initial data
        populate_tree()
        
        # Make dialog modal
        history_dialog.transient(self.root)
        history_dialog.grab_set()

    def print_wash_report(self, log_entry):
        """Membuat dan mencetak laporan hasil pencucian endoscope"""
        print_dialog = tk.Toplevel(self.root)
        print_dialog.title("Print Wash Report")
        print_dialog.geometry("400x150")
        print_dialog.configure(bg="#1f1f1f")
        
        # Tampilkan pertanyaan
        tk.Label(print_dialog, text="Apakah Anda ingin mencetak laporan?", 
                font=("Helvetica", 12), bg="#1f1f1f", fg="white").pack(pady=15)
        
        # Frame untuk tombol
        btn_frame = tk.Frame(print_dialog, bg="#1f1f1f")
        btn_frame.pack(pady=10)
        
        def print_yes():
            # Gunakan function yang sudah ada untuk membuat dan mencetak laporan
            timestamp = datetime.strptime(log_entry['timestamp_start'], "%Y-%m-%d %H:%M:%S")
            log_filename = f"{LOG_DIRECTORY}/washer_log_{timestamp.strftime('%Y%m%d_%H%M%S')}_{log_entry['scope_id']}.txt"
            
            # Pastikan file log sudah dibuat
            if not os.path.exists(log_filename):
                self.save_log_entry(log_entry)
                
            # Cetak file log
            self.print_report(log_filename)
            print_dialog.destroy()
        
        def print_no():
            print_dialog.destroy()
        
        ttk.Button(btn_frame, text="Ya", command=print_yes).pack(side=tk.LEFT, padx=20)
        ttk.Button(btn_frame, text="Tidak", command=print_no).pack(side=tk.LEFT, padx=20)
        
        # Jadikan dialog modal
        print_dialog.transient(self.root)
        print_dialog.grab_set()

    def get_platform(self):
        """Mendeteksi platform yang digunakan"""
        system = platform.system()
        if system == "Windows":
            return "windows"
        elif system == "Linux":
            # Cek apakah ini Raspberry Pi
            try:
                with open('/proc/device-tree/model', 'r') as f:
                    if 'Raspberry Pi' in f.read():
                        return "raspberry"
            except:
                pass
            return "linux"
        else:
            return "unknown"

    def print_file(self, filepath):
        """Mencetak file dengan metode yang sesuai berdasarkan platform"""
        platform_type = self.get_platform()
        
        try:
            if platform_type == "windows":
                if win32print and win32api:
                    default_printer = win32print.GetDefaultPrinter()
                    if default_printer:
                        win32api.ShellExecute(
                            0, 
                            "print", 
                            filepath, 
                            f'/d:"{default_printer}"', 
                            ".", 
                            0
                        )
                        return True, f"Dokumen dikirim ke printer {default_printer}"
                    else:
                        return False, "Tidak ada printer default yang dikonfigurasi"
                else:
                    return False, "Modul win32print tidak tersedia. Install dengan: pip install pywin32"
                    
            elif platform_type in ["raspberry", "linux"]:
                # Menggunakan lp command di Linux/Raspberry Pi
                result = subprocess.run(['lp', filepath], capture_output=True, text=True)
                if result.returncode == 0:
                    return True, "Dokumen dikirim ke printer default"
                else:
                    return False, f"Error printing: {result.stderr}"
            else:
                return False, f"Platform {platform_type} tidak didukung untuk printing"
        except Exception as e:
            return False, f"Error saat mencetak: {str(e)}"


    def print_report(self, filepath):
        """Mencetak file laporan"""
        try:
            # Buka file laporan untuk ditampilkan (preview)
            preview = tk.Toplevel(self.root)
            preview.title("Print Preview")
            preview.geometry("500x600")
            
            # Area teks untuk menampilkan isi file
            text_area = tk.Text(preview, wrap=tk.WORD, bg="white", font=("Courier", 10))
            scrollbar = tk.Scrollbar(preview, command=text_area.yview)
            text_area.configure(yscrollcommand=scrollbar.set)
            
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # Baca isi file
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Tampilkan isi file
            text_area.insert(tk.END, content)
            text_area.config(state=tk.DISABLED)  # Jadikan read-only
            
            # Frame untuk tombol
            btn_frame = tk.Frame(preview)
            btn_frame.pack(pady=10)
            
            # Status label untuk menampilkan hasil printing
            status_label = tk.Label(preview, text="", fg="black")
            status_label.pack(pady=5)
            
            # Fungsi untuk mengirim ke printer
            def send_to_printer():
                success, message = self.print_file(filepath)
                if success:
                    status_label.config(text=message, fg="green")
                    self.root.after(2000, preview.destroy)  # Tutup jendela setelah 2 detik jika berhasil
                else:
                    status_label.config(text=message, fg="red")
            
            ttk.Button(btn_frame, text="Print", command=send_to_printer).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="Close", command=preview.destroy).pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_frame, text="Save PDF", command=lambda: self.save_as_pdf(filepath)).pack(side=tk.LEFT, padx=10)
        
        except Exception as e:
            messagebox.showerror("Error", f"Gagal memuat file laporan: {str(e)}")

    # Tambahkan fungsi untuk menyimpan sebagai PDF
    def save_as_pdf(self, filepath):
        """Menyimpan file laporan sebagai PDF"""
        # Pada implementasi nyata, gunakan library seperti reportlab untuk Python
        # Untuk simplikasi, gunakan save as dialog
        pdf_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            title="Save Report as PDF"
        )
        
        if pdf_path:
            messagebox.showinfo("Save as PDF", f"Laporan akan disimpan sebagai {pdf_path}\n\nPada implementasi nyata, gunakan library PDF converter.")


if __name__ == '__main__':
    root = tk.Tk()
    app = WasherApp(root)
    root.mainloop()
    GPIO.cleanup()