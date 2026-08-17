#!/usr/bin/env python3
"""
Ticket Printing Application for Netum 58mm Thermal Printer
"""
from flask import Flask, request, render_template, jsonify
from datetime import datetime
import logging
from escpos.printer import Usb, Serial, Network
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass

from ticket_format import format_ticket, release_printer, print_lock
from ticket_validation import validate_submission
from credit_routes import create_credit_blueprint

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.getenv("CREDITS_PIN", "cursor-feedback-os"))

# Configuration
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'usb')  # 'usb', 'serial', 'network', or 'bluetooth'
USB_VENDOR = int(os.getenv('USB_VENDOR', '0x0416'), 16) if os.getenv('USB_VENDOR') else None
USB_PRODUCT = int(os.getenv('USB_PRODUCT', '0x5011'), 16) if os.getenv('USB_PRODUCT') else None
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')  # Default serial port
NETWORK_HOST = os.getenv('NETWORK_HOST', '192.168.1.100')

def get_printer():
    """Initialize and return the printer based on configuration"""
    try:
        if PRINTER_TYPE == 'usb':
            if USB_VENDOR and USB_PRODUCT:
                return Usb(USB_VENDOR, USB_PRODUCT)
            else:
                return Usb(0x0416, 0x5011)
        elif PRINTER_TYPE == 'serial' or PRINTER_TYPE == 'bluetooth':
            # For Bluetooth, use the serial backend via rfcomm
            port = SERIAL_PORT
            if PRINTER_TYPE == 'bluetooth':
                port = '/dev/rfcomm0'  # Default Bluetooth serial port
            return Serial(devfile=port, baudrate=9600)
        elif PRINTER_TYPE == 'network':
            return Network(NETWORK_HOST)
        else:
            raise ValueError(f"Unknown printer type: {PRINTER_TYPE}")
    except Exception as e:
        logger.error(f"Failed to initialize printer: {e}")
        logger.error(f"Try running: sudo rfcomm bind /dev/rfcomm0 [PRINTER_MAC_ADDRESS]")
        return None

app.register_blueprint(create_credit_blueprint(get_printer))

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/submit_ticket', methods=['POST'])
def submit_ticket():
    """Handle ticket submission"""
    try:
        data = request.json
        from_name = data.get('from_name', '')
        question = data.get('question', '')

        validation_error = validate_submission(from_name, question)
        if validation_error:
            return jsonify({'success': False, 'error': validation_error}), 400

        from_name = from_name.strip()
        question = question.strip()
        
        printer = get_printer()
        
        if printer is None:
            return jsonify({'success': False, 'error': 'Printer not available'}), 500
        
        success = format_ticket(printer, from_name, question)
        
        if success:
            logger.info(f"Ticket printed successfully from: {from_name}")
            return jsonify({'success': True, 'message': 'Ticket printed successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to print ticket'}), 500
            
    except Exception as e:
        logger.error(f"Error processing ticket submission: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        with print_lock:
            printer = get_printer()
            try:
                printer_status = printer is not None
                return jsonify({
                    'status': 'healthy',
                    'printer_connected': printer_status
                })
            finally:
                release_printer(printer)
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5000'))
    # USB printers fail on the second job if the debug reloader holds a duplicate process.
    use_reloader = os.getenv('FLASK_USE_RELOADER', 'false').lower() == 'true'
    app.run(host=host, port=port, debug=DEBUG, use_reloader=use_reloader)