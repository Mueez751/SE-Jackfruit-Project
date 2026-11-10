import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "blood_bank.db")

SECRET_KEY = "blood-bank-management-system-pes-2026-secret-key"
ALGORITHM = "HS256"
SESSION_EXPIRY_HOURS = 24

# Shelf life in days per component type
COMPONENT_SHELF_LIFE_DAYS = {
    "Whole Blood": 35,
    "Packed Red Cells": 42,
    "Platelets": 5,
    "Fresh Frozen Plasma": 365,
    "Cryoprecipitate": 365,
}

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

COMPONENT_TYPES = [
    "Whole Blood",
    "Packed Red Cells",
    "Platelets",
    "Fresh Frozen Plasma",
    "Cryoprecipitate",
]

# Biological Red Blood Cell / Whole Blood Compatibility Matrix
# Recipient blood group -> List of acceptable donor blood groups
RBC_COMPATIBILITY = {
    "O-": ["O-"],
    "O+": ["O+", "O-"],
    "A-": ["A-", "O-"],
    "A+": ["A+", "A-", "O+", "O-"],
    "B-": ["B-", "O-"],
    "B+": ["B+", "B-", "O+", "O-"],
    "AB-": ["AB-", "A-", "B-", "O-"],
    "AB+": ["AB+", "AB-", "A+", "A-", "B+", "B-", "O+", "O-"],
}

# Plasma Compatibility Matrix (reverse of RBC)
# Recipient blood group -> List of acceptable plasma donor groups
PLASMA_COMPATIBILITY = {
    "O-": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    "O+": ["O+", "A+", "B+", "AB+"],
    "A-": ["A-", "A+", "AB-", "AB+"],
    "A+": ["A+", "AB+"],
    "B-": ["B-", "B+", "AB-", "AB+"],
    "B+": ["B+", "AB+"],
    "AB-": ["AB-", "AB+"],
    "AB+": ["AB+"],
}

# Thresholds
LOW_STOCK_THRESHOLD = 5
UPCOMING_EXPIRY_DAYS = 3
PLATELET_EXPIRY_HOURS = 24

# Donor Eligibility Rules
MIN_DONOR_AGE = 18
MAX_DONOR_AGE = 65
MIN_DONOR_WEIGHT_KG = 50.0
MIN_HEMOGLOBIN_G_DL = 12.5
MIN_DONATION_INTERVAL_DAYS = 90
BP_SYSTOLIC_MIN = 100
BP_SYSTOLIC_MAX = 140
BP_DIASTOLIC_MIN = 60
BP_DIASTOLIC_MAX = 90
PULSE_MIN = 60
PULSE_MAX = 100
