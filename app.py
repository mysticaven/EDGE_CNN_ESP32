import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import serial
import serial.tools.list_ports
import socket
import time
import numpy as np
from PIL import Image
import threading
import os

# ================= CONFIG =================
BAUDRATE = 115200
IMG_SIZE = 32
WIFI_PORT = 3333
# =========================================

ser = None
selected_image = None
total_images = 0
correct_images = 0
processing = False


# ================= IMAGE =================
def prepare_image(path):
    """Convert image to 32x32 grayscale normalized array"""
    try:
        img = Image.open(path).convert("L")
        img = img.resize((IMG_SIZE, IMG_SIZE))
        arr = np.array(img, dtype=np.float32) / 255.0
        return np.round(arr * 128).astype(np.int8)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load image: {str(e)}")
        return None


# ================= SERIAL =================
def auto_connect_serial():
    """Auto-detect and connect to ESP32"""
    global ser
    ports = list(serial.tools.list_ports.comports())

    if not ports:
        update_status("No COM ports found", "red")
        return False

    for p in ports:
        try:
            s = serial.Serial(p.device, BAUDRATE, timeout=1)
            ser = s
            update_status(f"✓ Connected to {p.device}", "green")
            port_label.config(text=f"Port: {p.device}")
            return True
        except:
            pass

    update_status("❌ ESP32 Not Found", "red")
    return False


def update_status(msg, color="orange"):
    """Update status label safely"""
    status_label.config(text=msg, fg=color)
    root.update_idletasks()


# ================= ACCURACY ==============
def update_accuracy(pred):
    """Calculate and update accuracy"""
    global total_images, correct_images

    if not selected_image:
        return

    gt = "TIGER" if "tiger" in selected_image.lower() else "NOT_TIGER"
    total_images += 1

    if pred == gt:
        correct_images += 1

    acc = (correct_images / total_images) * 100 if total_images > 0 else 0
    acc_label.config(text=f"Accuracy: {acc:.1f}% ({correct_images}/{total_images})")


def reset_stats():
    """Reset accuracy statistics"""
    global total_images, correct_images
    total_images = 0
    correct_images = 0
    acc_label.config(text="Accuracy: ---")


# ================= SEND ===================
def send_image_worker():
    """Worker thread for sending image"""
    global processing, ser

    if not selected_image:
        messagebox.showwarning("Warning", "Please select an image first")
        return

    if mode.get() == "UART" and not ser:
        if not auto_connect_serial():
            messagebox.showerror("Error", "ESP32 not connected")
            return

    processing = True
    update_status("Processing...", "blue")
    send_btn.config(state="disabled")

    try:
        arr = prepare_image(selected_image)
        if arr is None:
            processing = False
            send_btn.config(state="normal")
            return

        # Reset result fields
        rx_label.config(text="---")
        infer_label.config(text="---")
        total_label.config(text="---")
        result_label.config(text="---")
        conf_label.config(text="---")

        img_name = os.path.basename(selected_image)
        img_label.config(text=f"Image: {img_name}")

        if mode.get() == "WIFI":
            send_wifi(arr)
        else:
            send_uart(arr)

    except Exception as e:
        messagebox.showerror("Error", f"Failed to send image: {str(e)}")
        update_status(f"Error: {str(e)}", "red")
    finally:
        processing = False
        send_btn.config(state="normal")


def send_uart(arr):
    """Send via UART"""
    if not ser or not ser.is_open:
        update_status("UART not connected", "red")
        return

    ser.write(arr.tobytes())
    update_status("Waiting for response...", "blue")
    read_response()


def send_wifi(arr):
    """Send via Wi-Fi"""
    ip = ip_entry.get().strip()
    if not ip:
        messagebox.showerror("Error", "Enter ESP32 IP address")
        return

    try:
        t0 = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, WIFI_PORT))
        sock.sendall(arr.tobytes())
        sock.close()
        tx_time = (time.time() - t0) * 1000
        tx_label.config(text=f"{tx_time:.2f} ms")
        update_status("Waiting for response...", "blue")
        read_response()
    except socket.timeout:
        messagebox.showerror("Error", "Connection timeout")
        update_status("Wi-Fi timeout", "red")
    except Exception as e:
        messagebox.showerror("Error", f"Wi-Fi Error: {str(e)}")
        update_status(f"Wi-Fi Error: {str(e)}", "red")


def read_response():
    """Read response from ESP32"""
    if not ser:
        return

    start = time.time()
    result_received = False

    while time.time() - start < 3:
        try:
            line = ser.readline().decode(errors="ignore").strip()

            if not line:
                continue

            if line.startswith("RX_us:"):
                rx = line.split(":")[1].strip()
                rx_label.config(text=f"{rx} µs")
            elif line.startswith("INFER_us:"):
                infer = line.split(":")[1].strip()
                infer_label.config(text=f"{infer} µs")
            elif line.startswith("TOTAL_us:"):
                total = line.split(":")[1].strip()
                total_label.config(text=f"{total} µs")
            elif line.startswith("RESULT:"):
                parts = line.split(":")
                if len(parts) >= 3:
                    cls = parts[1].strip()
                    conf = parts[2].strip()
                    color = "red" if cls == "TIGER" else "green"
                    result_label.config(text=cls, fg=color, font=("Arial", 16, "bold"))
                    conf_label.config(text=f"Confidence: {conf}%")
                    update_accuracy(cls)
                    update_status("✓ Complete", "green")
                    result_received = True
                    break
        except Exception as e:
            continue

    if not result_received:
        update_status("No response from ESP32", "orange")


def send_image():
    """Start image send in background thread"""
    thread = threading.Thread(target=send_image_worker, daemon=True)
    thread.start()


def select_image():
    """Select image file"""
    global selected_image
    file = filedialog.askopenfilename(
        filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp"), ("All Files", "*.*")]
    )
    if file:
        selected_image = file
        img_name = os.path.basename(file)
        img_label.config(text=f"Image: {img_name}")
        preview_image(file)


def preview_image(path):
    """Show image preview"""
    try:
        img = Image.open(path).convert("L")
        img.thumbnail((128, 128))
        img_array = np.array(img)
        # Update preview would require PhotoImage conversion
        preview_label.config(text=f"Size: {img_array.shape}")
    except:
        preview_label.config(text="Preview error")


# ================= UI =====================
root = tk.Tk()
root.title("ESP32 Tiger Detection System")
root.geometry("500x800")
root.resizable(False, False)

# Style
style = ttk.Style()
style.theme_use('clam')

# Header
header = tk.Frame(root, bg="#2c3e50", height=60)
header.pack(fill="x")
header.pack_propagate(False)
title = tk.Label(header, text="🐯 Tiger Detection", font=("Arial", 18, "bold"),
                 bg="#2c3e50", fg="white")
title.pack(pady=10)

# Main frame
main_frame = ttk.Frame(root, padding="15")
main_frame.pack(fill="both", expand=True)

# Mode selection
mode_frame = ttk.LabelFrame(main_frame, text="Connection Mode", padding="10")
mode_frame.pack(fill="x", pady=10)
mode = tk.StringVar(value="UART")
ttk.Radiobutton(mode_frame, text="UART (Serial)", variable=mode, value="UART").pack(anchor="w")
ttk.Radiobutton(mode_frame, text="Wi-Fi", variable=mode, value="WIFI").pack(anchor="w")

# Status
status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
status_frame.pack(fill="x", pady=10)
status_label = tk.Label(status_frame, text="Connecting...", fg="orange", font=("Arial", 10))
status_label.pack(anchor="w")
port_label = tk.Label(status_frame, text="Port: ---", font=("Arial", 9))
port_label.pack(anchor="w")

# Wi-Fi config
wifi_frame = ttk.LabelFrame(main_frame, text="Wi-Fi Settings", padding="10")
wifi_frame.pack(fill="x", pady=10)
ttk.Label(wifi_frame, text="ESP32 IP:").pack(anchor="w")
ip_entry = ttk.Entry(wifi_frame, width=25)
ip_entry.insert(0, "192.168.1.50")
ip_entry.pack(anchor="w", pady=5)

# Image selection
img_frame = ttk.LabelFrame(main_frame, text="Image Selection", padding="10")
img_frame.pack(fill="x", pady=10)
img_label = tk.Label(img_frame, text="Image: No image selected", font=("Arial", 9))
img_label.pack(anchor="w")
preview_label = tk.Label(img_frame, text="Preview: ---", font=("Arial", 9))
preview_label.pack(anchor="w", pady=5)
ttk.Button(img_frame, text="📁 Select Image", command=select_image).pack(fill="x", pady=5)

# Control buttons
ctrl_frame = ttk.Frame(main_frame)
ctrl_frame.pack(fill="x", pady=10)
send_btn = ttk.Button(ctrl_frame, text="🚀 Send & Measure", command=send_image)
send_btn.pack(fill="x", side="left", padx=2)
ttk.Button(ctrl_frame, text="🔄 Reconnect", command=auto_connect_serial).pack(fill="x", side="left", padx=2)

# Results
results_frame = ttk.LabelFrame(main_frame, text="Results", padding="10")
results_frame.pack(fill="both", expand=True, pady=10)

metrics_frame = ttk.Frame(results_frame)
metrics_frame.pack(fill="x")

result_label = tk.Label(results_frame, text="---", font=("Arial", 20, "bold"), fg="gray")
result_label.pack(pady=10)

conf_label = tk.Label(results_frame, text="Confidence: ---", font=("Arial", 11))
conf_label.pack()

ttk.Separator(results_frame, orient="horizontal").pack(fill="x", pady=10)

# Timing info
timing_frame = ttk.Frame(results_frame)
timing_frame.pack(fill="x")
ttk.Label(timing_frame, text="TX Time:").grid(row=0, column=0, sticky="w", padx=5)
tx_label = ttk.Label(timing_frame, text="---")
tx_label.grid(row=0, column=1, sticky="w")

ttk.Label(timing_frame, text="RX Time:").grid(row=1, column=0, sticky="w", padx=5)
rx_label = ttk.Label(timing_frame, text="---")
rx_label.grid(row=1, column=1, sticky="w")

ttk.Label(timing_frame, text="Inference:").grid(row=2, column=0, sticky="w", padx=5)
infer_label = ttk.Label(timing_frame, text="---")
infer_label.grid(row=2, column=1, sticky="w")

ttk.Label(timing_frame, text="Total:").grid(row=3, column=0, sticky="w", padx=5)
total_label = ttk.Label(timing_frame, text="---")
total_label.grid(row=3, column=1, sticky="w")

ttk.Separator(results_frame, orient="horizontal").pack(fill="x", pady=10)

# Accuracy
acc_frame = ttk.Frame(results_frame)
acc_frame.pack(fill="x")
acc_label = tk.Label(acc_frame, text="Accuracy: ---", font=("Arial", 11, "bold"))
acc_label.pack(anchor="w", pady=5)
ttk.Button(acc_frame, text="Reset Stats", command=reset_stats).pack(fill="x")

# Auto-connect on startup
root.after(500, auto_connect_serial)
root.mainloop()