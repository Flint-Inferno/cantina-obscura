import usb.core
import usb.util
import time

# --- CONSTANTS ---
# This is the "Secret Handshake" (Step 4)
INIT_COMMAND = [0x55, 0x0f, 0xb0, 0x01, 0x28, 0x63, 0x29, 0x20, 0x4c, 0x45, 0x47, 0x4f, 0x20, 0x32, 0x30, 0x31, 0x34, 0xf7, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

def setup_pad():
    # Find the pad by its specific IDs
    dev = usb.core.find(idVendor=0x0e6f, idProduct=0x0241)

    if dev is None:
        raise ValueError("Toy Pad not found! Check your connection.")

    # If the operating system is holding onto the device, tell it to let go
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)

    # Set the USB configuration
    dev.set_configuration()

    # SEND THE HANDSHAKE (The "Step 4" initialization)
    dev.write(1, INIT_COMMAND)
    print("Toy Pad Initialized and Ready!")
    return dev

def main():
    try:
        dev = setup_pad()
        
        print("Waiting for tags... (Press Ctrl+C to stop)")
        while True:
            try:
                # Read 32 bytes from the pad
                # 0x81 is the 'endpoint' where the pad sends its data
                data = dev.read(0x81, 32, timeout=500)
                
                # Check if this is an NFC event (Byte 0 = 0x56)
                if data[0] == 0x56:
                    pad_id = data[2]
                    action = "Placed" if data[5] == 0 else "Removed"
                    
                    # Extract the UID (Bytes 6 through 12)
                    uid = "-".join([format(b, '02X') for b in data[6:13]])
                    
                    if action == "Placed":
                        print(f"Tag Detected! Pad: {pad_id} | UID: {uid}")
                    else:
                        print(f"Tag Removed from Pad: {pad_id}")

            except usb.core.USBError:
                # This just means no data was sent during the timeout
                continue

    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()