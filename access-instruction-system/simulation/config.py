"""
Simulation & Evaluation Configuration Constants
================================================
All emission, cost, and operational parameters are declared here as named constants.
Never scatter magic numbers across experiment files — import from here.
"""

import os

# ----------- COST MODEL -----------
COST_PER_ATTEMPT_RS = 40.0          # Rs. per delivery attempt (fuel + labour)

# ----------- EMISSION MODEL -----------
EMISSION_G_CO2_PER_KM = 120.0       # g CO2 per km — based on India-typical petrol two-wheeler (approx 100-130 g/km)
AVG_KM_PER_ATTEMPT = 3.5            # km per attempt — last-mile urban average (Delhivery/Shadowfax ops estimate)

# ----------- SIMULATION PARAMETERS -----------
NUM_SEEDS = int(os.environ.get("NUM_SEEDS", "5"))  # Number of random seeds for multi-seed experiment
NUM_ADDRESSES = 400                  # Realistic address pool size (300-500)
NUM_DELIVERIES = 3000                # Delivery attempts per simulation run (2000-4000)
SIM_DAYS = 180                       # Time window for simulation: 6 continuous months
# ----------- AREA DISTRIBUTION & DIFFICULTY -----------
AREA_WEIGHTS = {
    "standalone house": 0.20,
    "apartment": 0.40,
    "gated community": 0.30,
    "industrial": 0.10
}

DIFFICULTY_MAP = {
    "standalone house": 0.12,   # Direct bell/knock, low friction
    "apartment": 0.38,          # Security guards, intercoms, floor access
    "gated community": 0.62,    # Multi-tier gate barrier, OTP/phone approval
    "industrial": 0.48          # Gate pass, security inspection, restrictive timings
}

# ----------- NAMED DRIVERS POOL (15-25 named drivers) -----------
NAMED_DRIVERS = [
    "R. Suresh", "K. Priya", "M. Rajesh", "A. Vignesh", "S. Anitha",
    "T. Karthik", "V. Deepa", "N. Murugan", "P. Lakshmi", "G. Prakash",
    "D. Kavitha", "B. Senthil", "C. Meena", "J. Anand", "E. Saravanan",
    "H. Shalini", "L. Dinesh", "R. Bhavani", "K. Balaji", "S. Divya"
]

# ----------- SLA PROMISED WINDOWS -----------
PROMISED_SLOTS = [
    "10:00-13:00 slot",
    "14:00-17:00 slot",
    "17:00-20:00 slot"
]

# ----------- CHANGE EVENT -----------
GROUND_TRUTH_CHANGE_FRACTION = 0.2   # Fraction of addresses whose true instruction changes at halfway point

# ----------- DRIVER / NOTE QUALITY -----------
DRIVER_ACCURACY_RATE = 0.9           # Fraction of driver notes that exactly capture true instruction
CUSTOMER_CONFIRM_RATE = 0.02         # Fraction of note-used deliveries where customer confirms (simulated)

# ----------- RTO LOGIC -----------
RTO_FRACTION_OF_FAILURES = 0.2       # 20% of failures become RTO (returned to origin)

# ----------- RESPONSIVE-VOLUME MODE -----------
# In responsive mode, a failed delivery triggers a re-attempt on a later day.
# SUCCESS / RTO stops further attempts for that address in this cohort.
MAX_REATTEMPTS_PER_ADDRESS = 3       # Max re-attempts before giving up (realistic ops limit)

