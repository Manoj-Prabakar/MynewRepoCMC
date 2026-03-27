import sys
import os
import pandas as pd

def process_excel(input_path: str, output_path: str, head_intent_value: str = "claims"):
    """
    - Renames 'Intent' to 'subIntent' on all sheets (if present).
    - Adds a new column 'HeadIntent' with constant value (default: 'claims') on all sheets.
    - Places 'HeadIntent' right after 'subIntent' when possible, otherwise appends at the end.
    - Writes all sheets back to a new Excel file.
    """
    # Read sheet names first
    try:
        xls = pd.ExcelFile(input_path, engine="openpyxl")
    except Exception as e:
        raise RuntimeError(f"Failed to open Excel file: {input_path}\n{e}")

    sheet_dfs = {}

    for sheet_name in xls.sheet_names:
        # Read each sheet with all data as string to avoid type surprises
        df = pd.read_excel(input_path, sheet_name=sheet_name, engine="openpyxl", dtype=str)

        # Normalize columns by stripping whitespace (optional but helpful)
        df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

        # 1) Rename Intent -> subIntent (only if 'Intent' exists and 'subIntent' doesn't already exist)
        if "intent" in df.columns and "subIntent" not in df.columns:
            df = df.rename(columns={"intent": "subIntent"})
        # If both exist, we keep them as-is (no destructive changes)

        # 2) Add HeadIntent column with constant value if not present
        if "HeadIntent" not in df.columns:
            # Decide position: right after 'subIntent' if it exists, else append at the end
            if "subIntent" in df.columns:
                insert_pos = list(df.columns).index("subIntent") + 1
                # Create the column at the end first, then reorder
                df["HeadIntent"] = head_intent_value
                cols = list(df.columns)
                # Move 'HeadIntent' to the target position
                cols.insert(insert_pos, cols.pop(cols.index("HeadIntent")))
                df = df.reindex(columns=cols)
            else:
                # No 'subIntent' column; just append 'HeadIntent'
                df["HeadIntent"] = head_intent_value
        else:
            # Ensure existing HeadIntent is filled with required value where empty
            df["HeadIntent"] = df["HeadIntent"].fillna(head_intent_value).replace({"": head_intent_value})

        sheet_dfs[sheet_name] = df

    # Save to new workbook
    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            for sheet_name, df in sheet_dfs.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    except Exception as e:
        raise RuntimeError(f"Failed to write Excel file: {output_path}\n{e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_intents.py <input.xlsx> [output.xlsx]")
        sys.exit(1)

    input_file = sys.argv[1]
    # Default output name next to input (e.g., input_updated.xlsx)
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        root, ext = os.path.splitext(input_file)
        output_file = f"{root}_updated1{ext or '.xlsx'}"

    process_excel(input_file, output_file, head_intent_value="Other Intents Playbook")
    print(f"✅ Done. Saved updated workbook to: {output_file}")
