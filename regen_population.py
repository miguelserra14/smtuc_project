from pathlib import Path
import sys
import geopandas as gpd
import pandas as pd
from datetime import datetime

sys.path.insert(0, str(Path('src').resolve()))

from visualizations import create_population_dashboard_html
from config import DEFAULT_BGRI_GPKG_PATH, DEFAULT_OUTPUT_GAP_CSV

# Since the original function expects merged GeoDataFrames instead of paths,
# we need to load and prepare the data here.
# Note: This reproduces the logic usually found in the main processing pipeline.

print("Regenerando population dashboard...")
html_path = Path("outputs/population/bgri.html")
html_path.parent.mkdir(parents=True, exist_ok=True)

try:
    # Load BGRI data
    print(f"Lendo {DEFAULT_BGRI_GPKG_PATH}...")
    bgri = gpd.read_file(DEFAULT_BGRI_GPKG_PATH)
    
    # Load Gap data
    print(f"Lendo {DEFAULT_OUTPUT_GAP_CSV}...")
    gaps = pd.read_csv(DEFAULT_OUTPUT_GAP_CSV)
    
    # Ensure DTBGRI is string for merging
    bgri['DTBGRI'] = bgri['DTBGRI'].astype(str)
    gaps['DTBGRI'] = gaps['DTBGRI'].astype(str)
    
    # Merge
    merged = bgri.merge(gaps, on='DTBGRI', how='inner')
    
    # For the dashboard, merged_2km is used for the inset map or specific filtering.
    # Here we'll use the same merged dataframe as a placeholder or filter if needed.
    # In the original test, it's a subset.
    merged_2km = merged.copy() 
    
    day_str = datetime.now().strftime("%Y-%m-%d")

    create_population_dashboard_html(
        output_path=html_path,
        merged=merged,
        merged_2km=merged_2km,
        day_str=day_str
    )
    print(f"? Population dashboard: {html_path}")
except Exception as e:
    print(f"? Error: {e}")
    import traceback
    traceback.print_exc()
