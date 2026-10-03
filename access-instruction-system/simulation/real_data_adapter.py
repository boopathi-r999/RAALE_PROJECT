"""
real_data_adapter.py — Adapter to swap real CSV data into the simulation
=========================================================================
Usage:
    python simulation/real_data_adapter.py --addresses path/to/real_addresses.csv
                                            --deliveries path/to/real_deliveries.csv

This script validates a real company CSV against the expected schema, computes
true_difficulty from historical outcomes, and writes the normalized files to
the simulation/ directory — replacing the synthetic data with minimal code change.

IMPORTANT: Anonymize personal data (customer names, exact addresses) before use.
"""

import argparse
import pandas as pd
import sys
import os

REQUIRED_ADDR_COLS = {"address_id", "raw_text", "area"}
REQUIRED_DEL_COLS  = {"delivery_id", "address_id", "timestamp"}
VALID_AREAS = {"apartment", "gated community", "industrial", "standalone house"}

def validate_and_transform_addresses(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_ADDR_COLS - set(df.columns)
    if missing:
        print(f"ERROR: Missing columns in addresses file: {missing}")
        sys.exit(1)

    # Normalize area values
    df["area"] = df["area"].str.lower().str.strip()
    invalid_areas = df[~df["area"].isin(VALID_AREAS)]["area"].unique()
    if len(invalid_areas) > 0:
        print(f"WARNING: Unknown area types found: {invalid_areas}")
        print(f"  Mapping unknown types to 'apartment' (most common). Review manually.")
        df["area"] = df["area"].apply(lambda x: x if x in VALID_AREAS else "apartment")

    # If true_difficulty not present, set to NaN (will be computed from deliveries)
    if "true_difficulty" not in df.columns:
        df["true_difficulty"] = float("nan")
    if "true_instruction" not in df.columns:
        df["true_instruction"] = "Unknown — to be filled from ops records"

    return df[["address_id", "raw_text", "area", "true_difficulty", "true_instruction"]]


def validate_and_transform_deliveries(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_DEL_COLS - set(df.columns)
    if missing:
        print(f"ERROR: Missing columns in deliveries file: {missing}")
        sys.exit(1)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df[["delivery_id", "address_id", "timestamp"]]


def compute_difficulty_from_outcomes(addresses: pd.DataFrame, deliveries: pd.DataFrame) -> pd.DataFrame:
    """
    Compute empirical failure rate per address from historical outcomes.
    Requires a 'outcome' column in deliveries ('SUCCESS', 'FAILED', 'RTO').
    """
    if "outcome" not in deliveries.columns:
        print("INFO: No 'outcome' column — cannot compute empirical difficulty. Using default 0.35.")
        addresses["true_difficulty"] = 0.35
        return addresses

    rates = (
        deliveries.groupby("address_id")
        .apply(lambda g: (g["outcome"] != "SUCCESS").sum() / len(g))
        .reset_index()
        .rename(columns={0: "computed_difficulty"})
    )
    addresses = addresses.merge(rates, on="address_id", how="left")
    mask = addresses["true_difficulty"].isna()
    addresses.loc[mask, "true_difficulty"] = addresses.loc[mask, "computed_difficulty"].fillna(0.35)
    addresses.drop(columns=["computed_difficulty"], inplace=True)
    return addresses


def main():
    parser = argparse.ArgumentParser(description="Adapter: Real CSV → Simulation Schema")
    parser.add_argument("--addresses", required=True, help="Path to real addresses CSV")
    parser.add_argument("--deliveries", required=True, help="Path to real deliveries CSV")
    parser.add_argument("--out-dir", default=os.path.dirname(__file__),
                        help="Output directory (default: simulation/)")
    args = parser.parse_args()

    print(f"Reading addresses: {args.addresses}")
    addr_df = pd.read_csv(args.addresses)
    print(f"Reading deliveries: {args.deliveries}")
    del_df = pd.read_csv(args.deliveries)

    addr_df = validate_and_transform_addresses(addr_df)
    del_df = validate_and_transform_deliveries(del_df)
    addr_df = compute_difficulty_from_outcomes(addr_df, del_df)

    out_addr = os.path.join(args.out_dir, "synthetic_addresses.csv")
    out_del  = os.path.join(args.out_dir, "synthetic_deliveries.csv")

    addr_df.to_csv(out_addr, index=False)
    del_df.to_csv(out_del, index=False)

    print(f"\n✓ Addresses written: {out_addr}  ({len(addr_df)} rows)")
    print(f"✓ Deliveries written: {out_del}  ({len(del_df)} rows)")
    print("\nYou can now run: python simulation/experiment.py")


if __name__ == "__main__":
    main()
